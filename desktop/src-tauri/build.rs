fn main() {
    // 显式登记自定义命令，让 Tauri 生成 allow-check-update / allow-install-update
    // 权限；否则本地页面能用，但 127.0.0.1 的 remote capability 会被 ACL 拒绝。
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&["check_update", "install_update"]),
        ),
    )
    .expect("failed to run tauri-build");
}
