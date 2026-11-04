+++
title = "Work"
description = "Selected work from our own bench: digital, power, communications and motors."
template = "work.html"

[extra]
label = "Work"
sig = "analog"
# The board renders (static/img/boards/<dir>/manifest.toml), linked to their product page.
boards = [
  { dir = "b153-donguru", view = "b153_hero", href = "/donguru/", sig = "usb" },
  { dir = "b200-re-port", view = "b200_hero", href = "/report/", sig = "analog" },
  { dir = "b125-eth-2fdcan", view = "b125_hero", href = "/can/", sig = "can" },
  { dir = "b135-usb-fdcan", view = "b135_hero", href = "/can/", sig = "can" },
]
# The bench projects, in this order (static/img/lab/<dir>/manifest.toml); sig colours the card's top edge.
items = [
  { dir = "laser-scanner-aoi", sig = "ctrl" },
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
]
+++
