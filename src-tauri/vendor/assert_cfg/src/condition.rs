use const_panic::PanicVal;

pub struct Cond {
    pub enabled: bool,
    /// A string with roughly this format:
    /// ```text
    /// - <stuff>
    /// ```
    /// which is how this condition is printed whenever an assertion fails.
    pub list_str: &'static str,
}

impl Cond {
    pub(crate) const fn enabled_count(cfgs: &[Cond]) -> usize {
        let mut enabled_cfgs = 0usize;
        for_range! {i in 0..cfgs.len() =>
            enabled_cfgs += cfgs[i].enabled as usize;
        }
        enabled_cfgs
    }

    #[track_caller]
    pub const fn panic_with_all<const LEN: usize>(message: &'static str, cfgs: [Cond; LEN]) -> ! {
        let cfg_list = map_to_panicval_array! {cfgs, |ref cfg| PanicVal::write_str(cfg.list_str) };

        const_panic::concat_panic(&[&[PanicVal::write_str(message)], &cfg_list]);
    }

    #[track_caller]
    pub const fn panic_with_enabled<const LEN: usize>(
        message: &'static str,
        cfgs: [Cond; LEN],
    ) -> ! {
        let cfg_list = map_to_panicval_array! {cfgs, |ref cfg| {
            if cfg.enabled {
                PanicVal::write_str(cfg.list_str)
            } else {
                PanicVal::EMPTY
            }
        }};

        const_panic::concat_panic(&[&[PanicVal::write_str(message)], &cfg_list]);
    }

    #[track_caller]
    pub const fn panic_with_disabled<const LEN: usize>(
        message: &'static str,
        cfgs: [Cond; LEN],
    ) -> ! {
        let cfg_list = map_to_panicval_array! {cfgs, |ref cfg| {
            if cfg.enabled {
                PanicVal::EMPTY
            } else {
                PanicVal::write_str(cfg.list_str)
            }
        }};

        const_panic::concat_panic(&[&[PanicVal::write_str(message)], &cfg_list]);
    }
}
