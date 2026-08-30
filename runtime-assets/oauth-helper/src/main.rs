use std::env;
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use oauth2::basic::BasicClient;
use oauth2::{
    AuthUrl, AuthorizationCode, ClientId, CsrfToken, EndpointNotSet, EndpointSet,
    PkceCodeChallenge, PkceCodeVerifier, RedirectUrl, RefreshToken, Scope, TokenResponse, TokenUrl,
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use url::Url;

const CLIENT_ID: &str = "65b708073fc0480ea92a077233ca87bd";
const REDIRECT_URI: &str = "http://127.0.0.1:0/login";
const MAX_CALLBACK_BYTES: usize = 8192;
const STATE_TTL_SECONDS: u64 = 600;

type Client = BasicClient<EndpointSet, EndpointNotSet, EndpointNotSet, EndpointNotSet, EndpointSet>;

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PendingState {
    csrf: String,
    pkce_verifier: String,
    created_at_unix: u64,
}

fn now() -> Result<u64, String> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| "system clock is before the Unix epoch".to_string())
}

fn client() -> Result<Client, String> {
    let authorization = AuthUrl::new("https://accounts.spotify.com/authorize".to_string())
        .map_err(|_| "invalid Spotify authorization URL".to_string())?;
    let token = TokenUrl::new("https://accounts.spotify.com/api/token".to_string())
        .map_err(|_| "invalid Spotify token URL".to_string())?;
    let redirect = RedirectUrl::new(REDIRECT_URI.to_string())
        .map_err(|_| "invalid headless redirect URL".to_string())?;
    Ok(BasicClient::new(ClientId::new(CLIENT_ID.to_string()))
        .set_auth_uri(authorization)
        .set_token_uri(token)
        .set_redirect_uri(redirect))
}

fn write_private(path: &Path, state: &PendingState) -> Result<(), String> {
    let mut options = OpenOptions::new();
    options.write(true).create(true).truncate(true).mode(0o600);
    let mut file = options
        .open(path)
        .map_err(|error| format!("state-create: {error}"))?;
    serde_json::to_writer(&mut file, state).map_err(|error| format!("state-write: {error}"))?;
    file.write_all(b"\n")
        .map_err(|error| format!("state-write: {error}"))?;
    file.sync_all()
        .map_err(|error| format!("state-sync: {error}"))
}

fn begin(state_path: &Path) -> Result<serde_json::Value, String> {
    let (challenge, verifier) = PkceCodeChallenge::new_random_sha256();
    let csrf = CsrfToken::new_random();
    let (authorization_url, _) = client()?
        .authorize_url(|| CsrfToken::new(csrf.secret().to_string()))
        .add_scope(Scope::new("streaming".to_string()))
        .set_pkce_challenge(challenge)
        .url();
    write_private(
        state_path,
        &PendingState {
            csrf: csrf.secret().to_string(),
            pkce_verifier: verifier.secret().to_string(),
            created_at_unix: now()?,
        },
    )?;
    Ok(json!({
        "schemaVersion": 1,
        "state": "waiting-for-callback",
        "authorizationUrl": authorization_url.as_str(),
        "expiresInSeconds": STATE_TTL_SECONDS,
        "upstream": {
            "librespot": "0.8.0",
            "oauthType": std::any::type_name::<librespot_oauth::OAuthToken>()
        }
    }))
}

fn callback_values(callback: &str) -> Result<(String, String), String> {
    if callback.len() > MAX_CALLBACK_BYTES {
        return Err("callback is too large".to_string());
    }
    let url = Url::parse(callback).map_err(|_| "callback is not a valid URL".to_string())?;
    if url.scheme() != "http" || url.host_str() != Some("127.0.0.1") || url.path() != "/login" {
        return Err("callback origin or path is invalid".to_string());
    }
    let code = url
        .query_pairs()
        .find(|(key, _)| key == "code")
        .map(|(_, value)| value.into_owned())
        .ok_or_else(|| "callback has no authorization code".to_string())?;
    let state = url
        .query_pairs()
        .find(|(key, _)| key == "state")
        .map(|(_, value)| value.into_owned())
        .ok_or_else(|| "callback has no state".to_string())?;
    Ok((code, state))
}

fn exchange(state_path: &Path, callback: &str) -> Result<serde_json::Value, String> {
    let encoded = fs::read(state_path).map_err(|error| format!("state-read: {error}"))?;
    let pending: PendingState =
        serde_json::from_slice(&encoded).map_err(|error| format!("state-parse: {error}"))?;
    if now()?.saturating_sub(pending.created_at_unix) > STATE_TTL_SECONDS {
        return Err("OAuth operation expired".to_string());
    }
    let (code, state) = callback_values(callback)?;
    if state != pending.csrf {
        return Err("OAuth callback state does not match".to_string());
    }
    let http = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(20))
        .build()
        .map_err(|error| format!("http-client: {error}"))?;
    let response = client()?
        .exchange_code(AuthorizationCode::new(code))
        .set_pkce_verifier(PkceCodeVerifier::new(pending.pkce_verifier))
        .request(&http)
        .map_err(|error| format!("token-exchange: {error}"))?;
    fs::remove_file(state_path).map_err(|error| format!("state-delete: {error}"))?;
    Ok(json!({
        "schemaVersion": 1,
        "state": "succeeded",
        "accessToken": response.access_token().secret(),
        "refreshToken": response.refresh_token().map(|item| item.secret()),
        "expiresInSeconds": response.expires_in().map(|item| item.as_secs()),
        "scopes": response.scopes().map(|items| items.iter().map(|item| item.to_string()).collect::<Vec<_>>()).unwrap_or_default()
    }))
}

fn refresh(refresh_token: &str) -> Result<serde_json::Value, String> {
    if refresh_token.is_empty() || refresh_token.len() > MAX_CALLBACK_BYTES {
        return Err("refresh token is missing or too large".to_string());
    }
    let http = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(20))
        .build()
        .map_err(|error| format!("http-client: {error}"))?;
    let response = client()?
        .exchange_refresh_token(&RefreshToken::new(refresh_token.to_string()))
        .request(&http)
        .map_err(|error| format!("token-refresh: {error}"))?;
    Ok(json!({
        "schemaVersion": 1,
        "state": "succeeded",
        "accessToken": response.access_token().secret(),
        "refreshToken": response.refresh_token().map(|item| item.secret()),
        "expiresInSeconds": response.expires_in().map(|item| item.as_secs()),
        "scopes": response.scopes().map(|items| items.iter().map(|item| item.to_string()).collect::<Vec<_>>()).unwrap_or_default()
    }))
}

fn read_bounded_stdin(name: &str) -> Result<String, String> {
    let mut value = String::new();
    std::io::stdin()
        .take((MAX_CALLBACK_BYTES + 1) as u64)
        .read_to_string(&mut value)
        .map_err(|_| format!("{name} could not be read"))?;
    if value.len() > MAX_CALLBACK_BYTES {
        return Err(format!("{name} is too large"));
    }
    Ok(value.trim().to_string())
}

fn execute(arguments: &[String]) -> Result<serde_json::Value, String> {
    if arguments.len() == 2 && arguments[0] == "refresh" && arguments[1] == "--token-stdin" {
        return refresh(&read_bounded_stdin("refresh token")?);
    }
    if arguments.len() < 3 || arguments[1] != "--state-file" {
        return Err(
            "usage: begin|exchange --state-file PATH [--callback-stdin] | refresh --token-stdin"
                .to_string(),
        );
    }
    let state_path = PathBuf::from(&arguments[2]);
    if state_path.as_os_str().is_empty() || state_path.is_dir() {
        return Err("state path is invalid".to_string());
    }
    match arguments[0].as_str() {
        "begin" if arguments.len() == 3 => begin(&state_path),
        "exchange" if arguments.len() == 4 && arguments[3] == "--callback-stdin" => {
            exchange(&state_path, &read_bounded_stdin("callback")?)
        }
        _ => Err(
            "usage: begin|exchange --state-file PATH [--callback-stdin] | refresh --token-stdin"
                .to_string(),
        ),
    }
}

fn main() {
    let arguments: Vec<String> = env::args().skip(1).collect();
    match execute(&arguments) {
        Ok(document) => {
            println!("{}", document);
        }
        Err(message) => {
            println!(
                "{}",
                json!({"schemaVersion": 1, "state": "failed", "message": message})
            );
            std::process::exit(1);
        }
    }
}
