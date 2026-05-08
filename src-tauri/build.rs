fn main() {
    // VPS 版：无 Windows DLL 搜索，无 Tauri
    println!("cargo:rerun-if-changed=build.rs");
}
