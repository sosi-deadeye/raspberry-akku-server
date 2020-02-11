#!/usr/bin/env python3

from path import pathlib
from binascii import unhexlify


VENDOR = '0x1d6b'
PRODUCT = '0x0104'
BCDDEVICE = '0x0100'
BCDUSB = '0x0200'

GADGET = {
    'idVendor': VENDOR,
    'idProduct': PRODUCT,
    'bcdDevice': BCDDEVICE,
    'bcdUSB': BCDUSB,
}

TEXT = {
    'serialnumber': "fedcba9876543210",
    'manufacturer': "Tobias Girstmair",
    'product': "iSticktoit.net USB Device",
}

CONFIG = {
    'configuration', "Config 1: ECM network",
}

CONFIG_C1 = {
    '250': 'MaxPower',
}

FUNCTIONS = {
    'protocol': '1',
    'subclass': '1',
    'report_length': 8,
    'report_desc': unhexlify('05010906a101050719e029e71500250175019508810295017508810395057501050819012905910295017503910395067508150025650507190029658100c0')
}

def write_sys(path, data_dict):
    path = Path(path)
    path.mkdir(exists_ok=True, parents=True)
    for file, text in data_dict.items():
        if isinstance(text, str):
            (path / file).write_text(text)
        elif isinstance(text, (bytes, bytearray))::
            (path / file).write_bytes(text)


gadget_path = Path('/sys/kernel/config/usb_gadget/isticktoit')
strings_path = gadget_path / 'strings/0x409'
configs_path = gadget_path / 'configs/c.1/strings/0x409'
configs_c1_path = configs_path.parent.parent
functions_path = gadget_path / 'functions/hid.usb0'

write_sys(gadget_path, GADGET)
write_sys(strings_path, TEXT)
write_sys(configs_path, CONFIG)
write_sys(configs_c1_path, CONFIG_C1)
write_sys(functions_path, FUNCTIONS)

functions_path.symlink_to(configs_c1_path, target_is_directory=True)
udc_path = gadget_path / 'UDC'
udc_path.write_text(
    '\n'.join(str(p.name) for p in Path('/sys/class/udc').iterdir())
)

"""
#!/bin/bash
cd /sys/kernel/config/usb_gadget/
mkdir -p isticktoit
cd isticktoit
echo 0x1d6b > idVendor # Linux Foundation
echo 0x0104 > idProduct # Multifunction Composite Gadget
echo 0x0100 > bcdDevice # v1.0.0
echo 0x0200 > bcdUSB # USB2
mkdir -p strings/0x409
echo "fedcba9876543210" > strings/0x409/serialnumber
echo "Tobias Girstmair" > strings/0x409/manufacturer
echo "iSticktoit.net USB Device" > strings/0x409/product
mkdir -p configs/c.1/strings/0x409
echo "Config 1: ECM network" > configs/c.1/strings/0x409/configuration
echo 250 > configs/c.1/MaxPower

# Add functions here
mkdir -p functions/hid.usb0
echo 1 > functions/hid.usb0/protocol
echo 1 > functions/hid.usb0/subclass
echo 8 > functions/hid.usb0/report_length
echo -ne \\x05\\x01\\x09\\x06\\xa1\\x01\\x05\\x07\\x19\\xe0\\x29\\xe7\\x15\\x00\\x25\\x01\\x75\\x01\\x95\\x08\\x81\\x02\\x95\\x01\\x75\\x08\\x81\\x03\\x95\\x05\\x75\\x01\\x05\\x08\\x19\\x01\\x29\\x05\\x91\\x02\\x95\\x01\\x75\\x03\\x91\\x03\\x95\\x06\\x75\\x08\\x15\\x00\\x25\\x65\\x05\\x07\\x19\\x00\\x29\\x65\\x81\\x00\\xc0 > functions/hid.usb0/report_desc
ln -s functions/hid.usb0 configs/c.1/
# End functions

ls /sys/class/udc > UDC
"""
