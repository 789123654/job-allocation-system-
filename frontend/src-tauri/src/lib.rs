mod store_crypto;

#[cfg(desktop)]
use tauri_plugin_updater::UpdaterExt;
#[cfg(desktop)]
use tauri::Emitter;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let builder = tauri::Builder::default().plugin(
    tauri_plugin_store::Builder::new()
      .default_serialize_fn(store_crypto::encrypt)
      .default_deserialize_fn(store_crypto::decrypt)
      .build(),
  );

  // Only present when built with `--features e2e-testing` (Phase 6 E2E CI job) — never in a
  // default/release build. See Cargo.toml's own comment on this dependency for why.
  #[cfg(feature = "e2e-testing")]
  let builder = builder.plugin(tauri_plugin_wdio_webdriver::init());

  // First app-defined command this project has ever exposed to the webview (2026-10-02,
  // update-confirmation dialog). Scoped to exactly this one command via
  // `src-tauri/permissions/confirm-restart.toml` + `capabilities/default.json` — never folded
  // into a broader permission set.
  #[cfg(desktop)]
  let builder = builder.invoke_handler(tauri::generate_handler![confirm_restart]);

  builder
    .setup(|app| {
      // Found during the updater's own review (2026-10-02): this was previously gated behind
      // `cfg!(debug_assertions)`, meaning NO logger was ever installed in a release build —
      // `log::error!`/`log::info!` calls (including check_for_update's below, the single most
      // security-relevant path in the app: a tampered-signature rejection would vanish without a
      // trace) silently went nowhere. Now always installed; only the verbosity differs, so
      // production stays quiet on routine noise but still captures warnings/errors to the real
      // on-disk log file (tauri-plugin-log's default targets include the OS log dir, not just
      // stdout — verified against the plugin's own source, not assumed).
      app.handle().plugin(
        tauri_plugin_log::Builder::default()
          .level(if cfg!(debug_assertions) {
            log::LevelFilter::Info
          } else {
            log::LevelFilter::Warn
          })
          .build(),
      )?;

      // Auto-update pipeline, Slice 2 — wiring only. The endpoint in tauri.conf.json is a
      // placeholder (`example.invalid`, never resolves), so `check()` always errors harmlessly
      // right now; this becomes a real, fully-automatic (no button, no prompt) check+install once
      // a later slice points `plugins.updater.endpoints` at a real hosted manifest.
      #[cfg(desktop)]
      {
        app.handle().plugin(tauri_plugin_updater::Builder::new().build())?;
        let handle = app.handle().clone();
        tauri::async_runtime::spawn(async move {
          if let Err(e) = check_for_update(handle).await {
            log::error!("update check failed: {e}");
          }
        });
      }

      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}

// Found in the attacker-pass review (2026-10-02), HIGH severity: `confirm_restart` originally had
// NO check that an update was ever actually staged — the permission file's description *claimed*
// "only after an update has already been downloaded", but nothing in code enforced it. Any
// webview-side code (an XSS, a compromised dependency, a future careless feature) could have
// called `invoke("confirm_restart")` at any time, on every launch, forcing a restart loop with no
// update pending — exactly the data-loss failure mode this whole feature exists to prevent, now
// reachable without any update involved at all. This flag is the real gate: set true only by
// check_for_update immediately before emitting `update-ready`, and required (not just hoped for)
// by confirm_restart before it will ever call app.restart().
#[cfg(desktop)]
static UPDATE_READY: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

#[cfg(desktop)]
async fn check_for_update(app: tauri::AppHandle) -> tauri_plugin_updater::Result<()> {
  if let Some(update) = app.updater()?.check().await? {
    log::info!("update {} available, downloading", update.version);
    update.download_and_install(|_, _| {}, || {}).await?;
    // Corrected 2026-10-02, 3-pass review: the install is already done and is NOT re-triggered by
    // confirm_restart below — only the restart itself is user-gated, never a second install. This
    // was previously an unconditional `app.restart()` here with zero user warning, found during
    // review to risk silently discarding unsaved work mid-edit. Now the frontend decides when,
    // via its own "Restart now?" dialog (update-ready-dialog.tsx) listening for this event.
    log::info!("update downloaded, waiting for user confirmation to restart");
    UPDATE_READY.store(true, std::sync::atomic::Ordering::SeqCst);
    if let Err(e) = app.emit("update-ready", ()) {
      log::error!("failed to emit update-ready event: {e}");
    }
  }
  Ok(())
}

// Reachable only after the frontend's "Restart Now" button — but the button alone is not the
// real gate (see UPDATE_READY above): any webview-side caller must find UPDATE_READY true, not
// just reach this function. A double-click or a replayed invoke after a real restart was already
// triggered is a one-shot no-op race on the restart call itself, never a second install
// (Business_Logic_Security_Cheat_Sheet.md "Prevent Race Conditions on Sensitive Operations",
// reviewed 2026-10-02). Takes no frontend-supplied arguments — nothing to validate/deserialize.
#[cfg(desktop)]
static RESTART_TRIGGERED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

// The actual ordering guarantee lives here, not just in a comment (test-critic pass, 2026-10-02):
// checks `update_ready` BEFORE ever touching `already_triggered`'s swap (a side effect) — a bogus
// call made before any update is staged must never touch `already_triggered` at all, or it would
// permanently lock out a later LEGITIMATE restart for the rest of this process's life. Takes
// plain `&AtomicBool` references (not the real statics) so this is testable with zero Tauri
// mocking — `confirm_restart` below is the only real caller.
fn try_claim_restart(
  update_ready: &std::sync::atomic::AtomicBool,
  already_triggered: &std::sync::atomic::AtomicBool,
) -> bool {
  if !update_ready.load(std::sync::atomic::Ordering::SeqCst) {
    return false;
  }
  !already_triggered.swap(true, std::sync::atomic::Ordering::SeqCst)
}

#[cfg(desktop)]
#[tauri::command]
fn confirm_restart(app: tauri::AppHandle) {
  if !try_claim_restart(&UPDATE_READY, &RESTART_TRIGGERED) {
    log::warn!("confirm_restart ignored — no update staged, or already triggered");
    return;
  }
  log::info!("user confirmed restart");
  app.restart();
}

#[cfg(test)]
mod tests {
  // Regression guard for the least-privilege fix (2026-10-02 review): the update check runs
  // entirely from Rust (`app.updater()?.check()`, never `invoke()`), so no capability should
  // ever grant the webview an `updater:*` permission — doing so adds attack surface (a future
  // XSS/content-injection bug could force a download+install+restart) with no legitimate use
  // this app's design actually needs.
  #[test]
  fn capabilities_do_not_grant_updater_permission() {
    let raw = include_str!("../capabilities/default.json");
    let json: serde_json::Value = serde_json::from_str(raw).expect("valid JSON");
    let permissions = json["permissions"].as_array().expect("permissions is an array");
    for p in permissions {
      let p = p.as_str().expect("permission is a string");
      assert!(
        !p.starts_with("updater:"),
        "capabilities/default.json grants '{p}' — the update check is Rust-only and must \
         never be exposed to the webview"
      );
    }
  }

  // Regression guard for the new confirm-restart permission (2026-10-02): its scope must stay
  // exactly ["confirm_restart"] — never widened (e.g. a careless `["*"]` or folding it into a
  // broader permission later), since this is the app's first-ever frontend-triggerable command.
  #[test]
  fn confirm_restart_permission_is_scoped_to_exactly_one_command() {
    let raw = include_str!("../permissions/confirm-restart.toml");
    let parsed: toml::Value = toml::from_str(raw).expect("valid TOML");
    let commands = parsed["permission"][0]["commands"]["allow"]
      .as_array()
      .expect("commands.allow is an array");
    let names: Vec<&str> = commands.iter().map(|c| c.as_str().expect("string")).collect();
    assert_eq!(
      names,
      vec!["confirm_restart"],
      "confirm-restart.toml's commands.allow should be exactly ['confirm_restart'], got {names:?}"
    );
  }

  // Regression guard for the HIGH-severity attacker-pass finding (2026-10-02): a restart must
  // never be allowed with no update actually staged. Exercises the REAL function (`try_claim_restart`,
  // real AtomicBools) rather than a stateless predicate — a test-critic pass caught that the first
  // version of this test only proved the boolean logic correct, not the ordering guarantee (that a
  // bogus pre-update call must never touch `already_triggered` at all).
  #[test]
  fn restart_only_allowed_when_update_is_ready_and_not_already_triggered() {
    use super::try_claim_restart;
    use std::sync::atomic::{AtomicBool, Ordering};

    let ready = AtomicBool::new(false);
    let triggered = AtomicBool::new(false);
    assert!(!try_claim_restart(&ready, &triggered), "no update staged — must never restart");
    assert!(
      !triggered.load(Ordering::SeqCst),
      "a bogus pre-update call must not touch already_triggered at all — would lock out a later legitimate restart"
    );

    ready.store(true, Ordering::SeqCst);
    assert!(try_claim_restart(&ready, &triggered), "update staged, first call — must be allowed");
    assert!(!try_claim_restart(&ready, &triggered), "second call must no-op, never restart twice");
  }
}
