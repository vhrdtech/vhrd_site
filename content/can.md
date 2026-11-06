+++
title = "CAN line"
description = "USB and Ethernet bridges to isolated CAN FD, CANnify boards, and the DB-9 and terminal-block adapters."

[extra]
label = "CAN"
sig = "can"
stub = true
og_image = "img/og/can-5.jpg"
twitter_image = "img/og/can-5.png"
og_image_alt = "An Ethernet to dual isolated CAN FD bridge PCB (B125), framed by red corner marks and the VHRD.TECH wordmark, with the headline “The CAN line · USB and Ethernet to isolated CAN FD”"
+++

To come: CANnify boards and the released adapters.

## B095, Ethernet to CAN

{{ <vh.fig stem="img/lab/b095-eth-can/b095" widths={[640]} sizes="(max-width: 75rem) 100vw, 72rem" alt="B095 prototype board with an Ethernet jack, two USB-C connectors, an SD card slot and a coin cell holder" n="1" caption="B095, the first Ethernet-to-CAN board and the design that led to today's CAN line: an Ethernet jack, two USB-C connectors, an SD card slot and a coin cell holder. Superseded by B125 and B135." /> }}

## B125, Ethernet to 2x isolated CAN FD

{{ <vh.fig stem="img/boards/b125-eth-2fdcan/b125_hero" widths={[640, 1280]} sizes="(max-width: 75rem) 100vw, 72rem" alt="B125 Ethernet to 2x ISO FDCAN bridge PCB, three-quarter view" n="2" caption="B125 rev B, the render: Ethernet to two isolated CAN FD channels on DB-9, with SD card logging and optional PoE or backplane power. Three rev A boards were hand-assembled 22 Apr 2024; commercial release: TBD." /> }}

## B135, USB to isolated CAN FD

<div class="fig-pair">

{{ <vh.fig stem="img/boards/b135-usb-fdcan/b135_hero" widths={[640, 1280]} sizes="(max-width: 52rem) 100vw, 36rem" alt="B135 USB HS to ISO FDCAN bridge PCB, three-quarter view" n="3" caption="B135 rev B, the render" /> }}
{{ <vh.fig stem="img/lab/b135-photo/b135b-photo" widths={[640, 1280]} sizes="(max-width: 52rem) 100vw, 36rem" alt="Assembled B135 rev B board on a bench: DB-9 connector, a transformer, a coin cell holder, a microSD slot and USB-C" n="4" caption="B135 rev B, the real board" /> }}

</div>
