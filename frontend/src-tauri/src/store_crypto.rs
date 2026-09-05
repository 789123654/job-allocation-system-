// Registered as tauri-plugin-store's default serialize/deserialize functions (lib.rs) — encrypts
// auth-session.json at rest instead of the plugin's default plaintext JSON. Phase 4 Step 3 decision
// (OWASP audit + user discussion): DPAPI now for Windows since it's free before any real
// distribution has happened; macOS/Linux fall back to plaintext here until Keychain/libsecret
// equivalents are added — do that before either platform is ever distributed to, so no legacy-format
// migration shim is ever needed (the same reasoning that made doing Windows now free).
use std::collections::HashMap;
use std::error::Error;

use serde_json::Value;

#[cfg(windows)]
pub fn encrypt(data: &HashMap<String, Value>) -> Result<Vec<u8>, Box<dyn Error + Send + Sync>> {
    let plain = serde_json::to_vec(data)?;
    Ok(windows_dpapi::encrypt_data(&plain, windows_dpapi::Scope::User, None)?)
}

#[cfg(windows)]
pub fn decrypt(bytes: &[u8]) -> Result<HashMap<String, Value>, Box<dyn Error + Send + Sync>> {
    let plain = windows_dpapi::decrypt_data(bytes, windows_dpapi::Scope::User, None)?;
    Ok(serde_json::from_slice(&plain)?)
}

#[cfg(not(windows))]
pub fn encrypt(data: &HashMap<String, Value>) -> Result<Vec<u8>, Box<dyn Error + Send + Sync>> {
    Ok(serde_json::to_vec(data)?)
}

#[cfg(not(windows))]
pub fn decrypt(bytes: &[u8]) -> Result<HashMap<String, Value>, Box<dyn Error + Send + Sync>> {
    Ok(serde_json::from_slice(bytes)?)
}
