use exact_units::{Fixed, prefix::One, units::{Joule, Torque}};

fn main() {
    // angle is a dimension: a torque is N·m per radian, not an energy
    let _ = Fixed::<Torque, One, i32>::new(5).convert::<Joule, One, i32>();
}
