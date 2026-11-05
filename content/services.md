+++
title = "Services"
description = "Electronics, firmware and the software around them, designed by the engineer who builds the VHRD products."

[extra]
label = "Services"
headline = "Engineering services"
sig = "ctrl"
+++

## Availability

Right now most of my time goes into VHRD's own products: [Donguru](@/donguru.md), [Pinsmith](@/pinsmith.md), [the CAN line](@/can.md) and [the software tools](@/software.md). I take on outside work only when a slot opens up, so I can't promise a start date.

You are still welcome to get in touch. I answer every message, even if it is "not right now". Sometimes a short call or a pointer to the right part is all a project needs.

## What I do

- **Board design.** Schematic and layout in KiCad: mixed-signal, power, USB, CAN FD, Ethernet with PoE, isolated interfaces.
- **Embedded firmware in Rust.** Bare-metal drivers and real-time firmware for STM32 and other microcontrollers, no-std and no-alloc.
- **Device communication.** Typed, versioned protocols between a device and a PC with {{ <vh.ref name="WireWeaver" /> }}, my open-source protocol and code generator.
- **Desktop and test tools.** GUIs, test jigs and production flashing for your boards, built on the same stack as {{ <vh.ref name="IOWeaver" /> }} and {{ <vh.ref name="RockFace" /> }}.
- **Power and motors.** BMS, power stages, 6-step and FOC motor controllers.
- **Design review.** A second look at your schematic, layout or firmware architecture before you order boards.

## See what I've built

- [Work](@/work.md): VHRD's own boards and the projects from the bench, from CAN FD bridges to motor controllers and a laser scanner.
- [Open source](@/open-source.md): the Rust crates and tools the products stand on, from register to GUI.
- [Software](@/software.md): {{ <vh.ref name="IOWeaver" /> }}, {{ <vh.ref name="RockFace" /> }} and {{ <vh.ref name="mx3" /> }}, with real runs of the command-line tools.

## How I work

1. You tell me what you are building and what you need.
2. I answer honestly: whether I have a slot, a rough estimate, or who else could help.
3. If it's a fit, you and I agree on scope and milestones. You get the design files, the source code and the documentation.

## Get in touch

Email {{ <vh.mail to="projects" subject="Project" /> }} with a few lines about your project, the timeline and what you need from me.
