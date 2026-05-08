use crate::Cond;

#[track_caller]
pub const fn assert_none<const LEN: usize>(cfgs: [Cond; LEN]) {
    if Cond::enabled_count(&cfgs) != 0 {
        Cond::panic_with_enabled("\nthese features must be disabled:\n", cfgs)
    }
}

/// Asserts that none of the passed-in features are enabled.
///
/// # Example
///
/// ```compile_fail
/// assert_cfg::none!{
///     feature = "foo",
///     all(feature = "bar", feature = "baz"),
///     feature = "qux",
/// }
///
/// ```
///
/// When the `"foo"` and `"bar"` features are enabled,
/// the above code produces this compile-time error:
/// ```text
/// error[E0080]: evaluation of constant value failed
///  --> src/assert_none.rs:15:1
///   |
/// 4 | / assert_cfg::none!{
/// 5 | |     feature = "foo",
/// 6 | |     all(feature = "bar", feature = "baz"),
/// 7 | |     feature = "qux",
/// 8 | | }
///   | |_^ the evaluated program panicked at '
/// these features must be disabled:
/// - `feature = "foo"`
/// - `all (feature = "bar", feature = "baz")`
/// ', src/assert_none.rs:4:1
///   |
///
///
/// ```
#[macro_export]
macro_rules! none {
    ($($args:tt)*) => {
        const _: () = $crate::__::assert_none(
            $crate::__priv_make_cond_array!($($args)*)
        );
    }
}
