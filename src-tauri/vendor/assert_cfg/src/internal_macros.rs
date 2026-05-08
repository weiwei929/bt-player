use const_panic::PanicVal;

macro_rules! for_range {
    ($pat:pat in $range:expr => $($code:tt)*) => {
        let core::ops::Range{mut start, end} = $range;

        while start < end {
            let $pat = start;

            $($code)*

            start+=1;
        }
    };
}

macro_rules! map_to_panicval_array {
    ($arr:expr, |ref $elem:ident| $elem_init:expr) => {{
        let arr = $arr;
        let mut out = crate::internal_macros::new_panicval_array(&arr);

        for_range! {i in 0..arr.len() =>
            let $elem = &arr[i];
            out[i] = $elem_init;
        }

        out
    }};
}

pub(crate) const fn new_panicval_array<T, const LEN: usize>(
    _: &[T; LEN],
) -> [PanicVal<'static>; LEN] {
    [PanicVal::EMPTY; LEN]
}

#[doc(hidden)]
#[macro_export]
macro_rules! __priv_make_cond_array {
    ($($args:tt)*) => (
        $crate::__priv_make_cond_array_inner!([] [$($args)*])
    )
}

#[doc(hidden)]
#[macro_export]
macro_rules! __priv_make_cond_array_inner {
    (
        [ $($prev:tt)* ]
        [ $ident:ident = $feature_eq:expr $(, $($rem:tt)*)? ]
    ) => {
        $crate::__priv_make_cond_array_inner!{
            [$($prev)* ($ident = $feature_eq) ]
            [$($($rem)*)?]
        }
    };
    (
        [ $($prev:tt)* ]
        [ $ident:ident ($($paren:tt)*)  $(, $($rem:tt)*)? ]
    ) => {
        $crate::__priv_make_cond_array_inner!{
            [$($prev)* ($ident($($paren)*)) ]
            [$($($rem)*)?]
        }
    };
    (
        [$(( $($cfg:tt)* ))*]
        []
    ) => ({
        use $crate::__::{Cond, concat, cfg};

        [
            $(
                Cond {
                    enabled: cfg!( $($cfg)* ),
                    list_str: concat!("- `", stringify!($($cfg)*), "`\n"),
                },
            )*
        ]
    });
}
