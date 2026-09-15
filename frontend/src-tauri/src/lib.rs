mod store_crypto;

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

  builder
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
