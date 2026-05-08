use crate::Cond;

#[track_caller]
pub const fn assert_exactly_one<const LEN: usize>(cfgs: [Cond; LEN]) {
    match Cond::enabled_count(&cfgs) {
        0 => Cond::panic_with_all(
            "\nno features were enabled, expected one of these to be enabled:\n",
            cfgs,
        ),
        1 => (),
        _many => Cond::panic_with_enabled(
            "\ntoo many features were enabled, only one of them can be enabled:\n",
            cfgs,
        ),
    }
}

/// Asserts that exactly one of the passed-in features is enabled.
///
/// # Example
///
/// ### No enabled features
///
/// This example demonstrates the error message when no features are enabled.
///
/// ```compile_fail
/// assert_cfg::exactly_one!{
///     feature = "std",
///     feature = "no_std",
/// }
///
/// ```
///
/// When no feature is enabled, the above code produces this compile-time error:
/// ```text
/// error[E0080]: evaluation of constant value failed
///  --> src/lib.rs:10:1
///   |
/// 4 | / assert_cfg::exactly_one!{
/// 5 | |     feature = "std",
/// 6 | |     feature = "no_std",
/// 7 | | }
///   | |_^ the evaluated program panicked at '
/// no features were enabled, expected one of these to be enabled:
/// - `feature = "std"`
/// - `feature = "no_std"`
///
/// ```
///
/// ### Too many enabled features
///
/// This example demonstrates the error message when more than one feature is enabled.
///
/// ```compile_fail
/// assert_cfg::exactly_one!{
///     feature = "foo",
///     not(feature = "qux"),
///     feature = "hello",
/// }
/// ```
///
/// When the `"foo"` and `"bar"` features are enabled,
/// the above code produces this compile-time error:
/// ```text
/// error[E0080]: evaluation of constant value failed
///  --> src/assert_exactly_one.rs:55:1
///   |
/// 4 | / assert_cfg::exactly_one!{
/// 5 | |     feature = "foo",
/// 6 | |     not(feature = "qux"),
/// 7 | |     feature = "hello",
/// 8 | | }
///   | |_^ the evaluated program panicked at '
/// too many features were enabled, only one of them can be enabled:
/// - `feature = "foo"`
/// - `not (feature = "qux")`
/// ', src/assert_exactly_one.rs:4:1
///   |
///
/// ```
#[macro_export]
macro_rules! exactly_one {
    ($($args:tt)*) => {
        const _: () = $crate::__::assert_exactly_one(
            $crate::__priv_make_cond_array!($($args)*)
        );
    }
}
