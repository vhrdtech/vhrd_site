#![no_std]

use ww_api::prelude::*;

#[ww_api_root]
pub trait BlinkyApi {
    fn led_on(#[default = 255] brightness: u8);
    fn led_off();
}
