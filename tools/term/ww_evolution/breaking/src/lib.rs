#![no_std]

use wire_weaver::prelude::*;

#[ww_api_root]
pub trait BlinkyApi {
    fn led_on(brightness: u8);
    fn led_off();
}
