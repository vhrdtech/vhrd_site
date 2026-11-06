#![no_std]

use wire_weaver::prelude::*;

#[ww_api_root]
pub trait BlinkyApi {
    fn led_on(#[default = 255] brightness: u8);
    fn led_off();
}
