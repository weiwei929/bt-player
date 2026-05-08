[![Rust](https://github.com/rodrimati1992/assert_cfg/workflows/Rust/badge.svg)](https://github.com/rodrimati1992/assert_cfg/actions)
[![crates-io](https://img.shields.io/crates/v/assert_cfg.svg)](https://crates.io/crates/assert_cfg)
[![api-docs](https://docs.rs/assert_cfg/badge.svg)](https://docs.rs/assert_cfg/*)

Static assertions for crate features, with informative errors.

The macros from this crate print which specific features are responsible for
the assertion failure.

# Examples

### Exactly one feature

This example demonstrates the [`exactly_one`] macro,
which asserts that exactly one of the listed features is enabled.


```compile_fail
assert_cfg::exactly_one!{
    feature = "foo",
    feature = "bar",
    feature = "qux",
}
```

When the `"foo"` and `"bar"` features are enabled,
the above code produces this compile-time error:
```text
error[E0080]: evaluation of constant value failed
 --> src/lib.rs:15:1
  |
4 | / assert_cfg::exactly_one!{
5 | |     feature = "foo",
6 | |     feature = "bar",
7 | |     feature = "qux",
8 | | }
  | |_^ the evaluated program panicked at '
too many features were enabled, only one of them can be enabled:
- `feature = "foo"`
- `feature = "bar"`

```


# No-std support

`assert_cfg` is `#![no_std]`, it can be used anywhere Rust can be used.

# Minimum Supported Rust Version

This requires Rust 1.57.0, because it uses the `panic` macro in a const context.



[`exactly_one`]: https://docs.rs/assert_cfg/latest/assert_cfg/macro.exactly_one.html
