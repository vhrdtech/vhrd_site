+++
title = "Work"
description = "Selected work from our own bench: digital, power, communications and motors."
template = "work.html"

[extra]
label = "Work"
sig = "analog"
# The board renders (static/img/boards/<dir>/manifest.toml), linked to their product page; pitch is the card's line,
# photo a photo of the real board shown next to its render (static/img/lab/<photo>/manifest.toml).
boards = [
  { dir = "b153-donguru", view = "b153_hero", href = "/donguru/", sig = "usb" },
  { dir = "b200-re-port", view = "b200_hero", href = "/pinsmith/", sig = "analog" },
  { dir = "b125-eth-2fdcan", view = "b125_hero", href = "/can/", sig = "can" },
  { dir = "b135-usb-fdcan", view = "b135_hero", href = "/can/", sig = "can", photo = "b135-photo" },
  { dir = "b129-cannify-micro", view = "b129_hero", href = "/can/", sig = "can", pitch = "A breadboard-friendly CAN node: an STM32G0, a CAN transceiver and a DC-DC converter for up to 48 V in. It runs IO firmware or your own." },
  { dir = "b133-d600plus-control", view = "b133_hero", href = "/lab/", sig = "ctrl", pitch = "A control board for the lab's D600Plus pick-and-place machine: an STM32H743 with Ethernet, USB-C and CAN." },
]
# The bench projects, in this order (static/img/lab/<dir>/manifest.toml); sig colours the card's top edge,
# all shows every image of the manifest instead of the first.
items = [
  { dir = "laser-scanner-aoi", sig = "ctrl" },
  { dir = "just-screw-it", sig = "bus", all = true },
  { dir = "motor-controller-6step-foc", sig = "power" },
  { dir = "bms-50a-100a", sig = "power" },
  { dir = "torque-sensor-afe", sig = "analog" },
  { dir = "can-servo-controller", sig = "can" },
  { dir = "raspberry-pi-carrier", sig = "can" },
  { dir = "thermocouple-afe", sig = "analog" },
  { dir = "rockface", sig = "ctrl" },
  { dir = "propeller-test-stand", sig = "power" },
  { dir = "granite-cnc", sig = "bus", badge = "Design, not built" },
  { dir = "eskate-elongboard", sig = "power" },
  { dir = "vg095-eth-can", sig = "can" },
]
+++
