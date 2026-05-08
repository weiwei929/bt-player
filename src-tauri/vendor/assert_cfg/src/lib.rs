//! Static assertions for crate features, with informative errors.
//!
//! The macros from this crate print which specific features are responsible for
//! the assertion failure.
//!
//! # Examples
//!
//! ### Exactly one feature
//!
//! This example demonstrates the [`exactly_one`] macro,
//! which asserts that exactly one of the listed features is enabled.
//!
//!
//! ```compile_fail
//! assert_cfg::exactly_one!{
//!     feature = "foo",
//!     feature = "bar",
//!     feature = "qux",
//! }
//! ```
//!
//! When the `"foo"` and `"bar"` features are enabled,
//! the above code produces this compile-time error:
//! ```text
//! error[E0080]: evaluation of constant value failed
//!  --> src/lib.rs:15:1
//!   |
//! 4 | / assert_cfg::exactly_one!{
//! 5 | |     feature = "foo",
//! 6 | |     feature = "bar",
//! 7 | |     feature = "qux",
//! 8 | | }
//!   | |_^ the evaluated program panicked at '
//! too many features were enabled, only one of them can be enabled:
//! - `feature = "foo"`
//! - `feature = "bar"`
//!
//! ```
//!
//!
//! # No-std support
//!
//! `assert_cfg` is `#![no_std]`, it can be used anywhere Rust can be used.
//!
//! # Minimum Supported Rust Version
//!
//! This requires Rust 1.57.0, because it uses the `panic` macro in a const context.
//!
//!
//!
//! [`exactly_one`]: crate::exactly_one

#![no_std]

#[doc(hidden)]
pub mod __ {
    pub use core::{cfg, concat};

    pub use crate::{
        assert_all::assert_all, assert_any::assert_any, assert_exactly_one::assert_exactly_one,
        assert_none::assert_none, condition::Cond,
    };
}

#[macro_use]
mod internal_macros;

mod assert_all;
mod assert_any;
mod assert_exactly_one;
mod assert_none;
mod condition;

use crate::condition::Cond;

#[cfg(all(not(feature = "__test"), test))]
compile_error!(r#"The "__test" feature must be enabled to run tests"#);

#[cfg(doctest)]
#[doc = include_str!("../README.md")]
pub struct ReadmeTest;
