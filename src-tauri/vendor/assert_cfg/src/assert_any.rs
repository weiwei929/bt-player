use crate::Cond;

#[track_caller]
pub const fn assert_any<const LEN: usize>(cfgs: [Cond; LEN]) {
    if LEN == 0 {
        panic!("at least one feature is required for this assertion")
    } else if Cond::enabled_count(&cfgs) == 0 {
        Cond::panic_with_all("\nat least one of these features must be enabled:\n", cfgs)
    }
}

/// Asserts that any of the passed-in features are enabled.
///
/// # Example
///
/// This example demonstrates the error message when not enough features are enabled.
///
/// ```compile_fail
/// assert_cfg::any!{
///     feature = "qux",
///     feature = "bob",
/// }
/// ```
///
/// When no feature is enabled, the above code produces this compile-time error:
/// ```text
/// error[E0080]: evaluation of constant value failed
///  --> src/assert_any.rs:20:1
///   |
/// 4 | / assert_cfg::any!{
/// 5 | |     feature = "qux",
/// 6 | |     feature = "bob",
/// 7 | | }
///   | |_^ the evaluated program panicked at '
/// at least one of these features must be enabled:
/// - `feature = "qux"`
/// - `feature = "bob"`
/// ', src/assert_any.rs:4:1///
/// ```
#[macro_export]
macro_rules! any {
    ($($args:tt)*) => {
        const _: () = $crate::__::assert_any(
            $crate::__priv_make_cond_array!($($args)*)
        );
    }
}
