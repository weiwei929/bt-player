use crate::Cond;

#[track_caller]
pub const fn assert_all<const LEN: usize>(cfgs: [Cond; LEN]) {
    if Cond::enabled_count(&cfgs) != LEN {
        Cond::panic_with_disabled(
            "\ntoo few features are enabled, these need to be enabled:\n",
            cfgs,
        )
    }
}

/// Asserts that all of the passed-in features are enabled.
///
/// # Example
///
/// This example demonstrates the error message when not enough features are enabled.
///
/// ```compile_fail
/// assert_cfg::all!{
///     any(feature = "foo", feature = "bar"),
///     feature = "qux",
/// }
/// ```
///
/// When only the `"foo"` feature is enabled,
/// the above code produces this compile-time error:
/// ```text
/// error[E0080]: evaluation of constant value failed
///  --> src/assert_all.rs:20:1
///   |
/// 4 | / assert_cfg::all!{
/// 5 | |     any(feature = "foo", feature = "bar"),
/// 6 | |     feature = "qux",
/// 7 | | }
///   | |_^ the evaluated program panicked at '
/// too few features are enabled, these need to be enabled:
/// - `feature = "qux"`
/// ', src/assert_all.rs:4:1
///   |
///
///
/// ```
#[macro_export]
macro_rules! all {
    ($($args:tt)*) => {
        const _: () = $crate::__::assert_all(
            $crate::__priv_make_cond_array!($($args)*)
        );
    }
}
