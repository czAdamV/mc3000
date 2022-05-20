#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# vim:fenc=utf-8:ts=8:et:sw=4:sts=4
#
# Copyright © 2017 jpk <jpk@goatpr0n.de>
#
# Distributed under terms of the MIT license.

"""
MC3000 USB interface library
----------------------------

USB Interface library to communicate with the SKYRC MC3000 Battery Analyzer/Charger.
"""

from struct import pack, unpack
from collections import namedtuple
import json
import usb.core
import usb.util


#: Machine response data
MACHINE_INFO_STRUCT = '>3xBBBBBBBBBBBBB6sBBhBBBBbB'
#: Tuple for device information
MachineInfo = namedtuple('machine_info',
                         ['Sys_Mem1', 'Sys_Mem2', 'Sys_Mem3', 'Sys_Mem4', 'Sys_Advance',
                          'Sys_tUnit', 'Sys_Buzzer_Tone', 'Sys_Life_Hide', 'Sys_LiHv_Hide',
                          'Sys_Eneloop_Hide', 'Sys_NiZn_Hide', 'Sys_Lcd_time', 'Sys_Min_Input',
                          'core_type', 'upgrade_type', 'is_encrypted', 'customer_id',
                          'language_id', 'software_version_hi', 'software_version_lo',
                          'hardware_version', 'reserved', 'checksum', 'software_version',
                          'machine_id'])

# Progress status response data
PROGRESS_STATUS_STRUCT = '>xBBxBBhhhhhhxxxxxxB38xB'
#: Tuple for charging progress information
ProgressInfo = namedtuple('charge_data',
                          ['slot', 'type', 'status', 'work', 'work_time', 'voltage', 'current',
                           'caps', 'bat_tem', 'inner_resistance', 'caps_decimal', 'checksum',
                           'dcaps'])

#: Battery response data
CHARGE_DATA_STRUCT = '>xBBBBhhhhhhhBBBBBhBhB33xB'
#: Tuple for battery operational configuration
Battery = namedtuple('battery_data',
                     ['slot', 'work', 'type', 'mode', 'caps', 'cur', 'dCur', 'cut_volt',
                      'end_volt', 'end_cur', 'end_dcur', 'cycle_count', 'cycle_delay',
                      'cycle_mode', 'peak_sense', 'trickle', 'hold_volt', 'cut_temp', 'cut_time',
                      'tem_unit', 'checksum'])

#: Charger operational modes
BATTERY_MODE = {
    0: 'Charging',
    1: 'Refreshing',
    2: 'Storing', # Storage
    3: 'Discharging',
    4: 'Cycling',
}
#: Battery types supported by the MC3000
BATTERY_TYPE = {
    0: 'LiIon',
    1: 'LiFe',
    2: 'LiHV',
    3: 'NiMH',
    4: 'NiCd',
    5: 'NiZn',
    6: 'Eneloop',
}
#: Cycle modes for charge cycling operations
CYCLE_MODE = {
    0: 'C>D',
    1: 'C>D>C',
    2: 'D>C',
    3: 'D>C>C'
}
#: Progress status during cycling
CYCLE_STATUS = {
    0: '',
    1: '>Charge',
    2: '>DisCharge',
    3: '>Resting',
    4: 'FINISH'
}
#: Temperature units
TEM_UNIT = ('°C', '°F')
#: MC3000 operational status
WORK_PROGRESS = {
    1: 'Charging',
    4: 'Finished'
}

#: Data protocol header
CMD_PACKET_HEADER = b'\x0f\x04'
#: Data protocol tail
CMD_PACKET_TAIL = b'\xff\xff'

#: Data protocol progress data opcode
CMD_READ_PROGRESS_DATA = b'\x55' # 85
#: Data protocol charger configuration opcode
CMD_READ_CHARGER_DATA = b'\x5f' # 95


class MC3000(object):
    """MC3000 USB Interface class

    During initialization, the interface class with search for the USB device and will claim the
    device to communicate.

    After the device was claimed, :func:`get_machine_info` and :func:`get_battery_data` is
    called.
    """

    def __init__(self):
        self.device = usb.core.find(idVendor=0x0000, idProduct=0x0001)
        if not self.device:
            raise Exception('Device not found')
        #: check if device is already claimed and free it
        for config in self.device:
            for config_index in range(config.bNumInterfaces):
                if self.device.is_kernel_driver_active(config_index):
                    self.device.detach_kernel_driver(config_index)
        self.device.set_configuration()
        self.config = self.device.get_active_configuration()
        self.interface = self.config[(0, 0)]
        usb.util.claim_interface(self.device, self.interface)

        self.device.reset()

        self.ep_in = self.device[0][(0, 0)][0]
        self.ep_out = self.device[0][(0, 0)][1]

        #: Holds the device information. Gets pulicated by :func:`get_machine_info`
        self.machine_info = self.get_machine_info()
        #: Holds the active slot configuration. Gets publicated by :func:`get_battery_data`
        self.battery_data = self.get_battery_data()

    def close(self):
        """Free up the resources claimed by the library
        """
        usb.util.dispose_resources(self.device)

    def get_machine_info(self):
        """Request the device configuration.

        The packet ``\\x0f\\x04\\x5a\\x00\\x04\\x5e\\xff\\xff`` is send to the device with
        :func:`send_raw` and response is stored in :attr:`machine_info` of type
        :data:`MachineInfo`.

        Calling this method will also update the :attr:`machine_info`.

        :rtype: :data:`MachineInfo`
        """
        packet = b'\x0f\x04\x5a\x00\x04\x5e\xff\xff'
        self.send_raw(packet)
        response = self.read()

        crc = 0
        machine_id = ''
        # Calculate a device specific checksum (*crc*) and *machine_id*.
        for j in range(16):
            if j < 15:
                crc += response[16 + j]
            text2 = '{:X}'.format(response[16 + j])
            machine_id += '{s:{c}>{n}}'.format(s=text2, n=2, c='0')

        data = unpack(MACHINE_INFO_STRUCT, response[:32])
        machine = MachineInfo(*data, 0, machine_id)
        machine = machine._replace(software_version='{:.2f}'.format(machine.software_version_hi \
                * 1.0 + machine.software_version_lo * 1.0 / 100.0))
        machine = machine._replace(core_type=machine.core_type.decode('utf-8', errors='replace'))
        machine = machine._replace(Sys_Advance=machine.Sys_Advance == 1)
        machine = machine._replace(Sys_tUnit=TEM_UNIT[machine.Sys_tUnit])
        machine = machine._replace(Sys_Life_Hide=machine.Sys_Life_Hide == 1)
        machine = machine._replace(Sys_LiHv_Hide=machine.Sys_LiHv_Hide == 1)
        machine = machine._replace(Sys_Eneloop_Hide=machine.Sys_Eneloop_Hide == 1)
        machine = machine._replace(Sys_NiZn_Hide=machine.Sys_NiZn_Hide == 1)
        machine = machine._replace(is_encrypted=machine.is_encrypted == 1)

        # Prevent crc to be negative by masking it
        crc = ~crc & 0xff
        crc += 1
        if not crc == machine.checksum:
            raise Exception('Checksum error in device data packet')
        self.machine_info = machine
        return self.machine_info

    @staticmethod
    def packet_checksum(data_packet):
        """Calculate the checksum for *data_packet*.

        :param data_packet: data packet to be verified
        :type data_packet: bytes
        :rtype: string of *crc*
        """
        crc = 0
        for i in range(0, 63):
            crc += data_packet[i]
            crc &= 0xff
        return crc

    def start(self):
        """Start the charging progress.

        The packet ``\\x0f\\x03\\x05\\x00\\x05\\xff\\xff`` is send to the device with
        :func:`send_raw`. No response is expected.
        """

        packet = b'\x0f\x03\x05\x00\x05\xff\xff'
        self.send_raw(packet)

    def stop(self):
        """Stop the charging progress.

        The packet ``\\x0f\\x03\\xfe\\x00\\xfe\\xff\\xff`` is send to the device with
        :func:`send_raw`. No response is expected.
        """
        packet = b'\x0f\x03\xfe\x00\xfe\xff\xff'
        self.send_raw(packet)

    def get_battery_data(self):
        """Request the slot charging configuration.

        A request for each battery slot is send to the device, with the ``CMD_READ_CHARGER_DATA``
        opcode and the corresponding *slot* as arguments to the function :func:`send`.

        :rtype: list of :data:`Battery`.
        """
        batteries = []
        for slot in range(4):
            self.send(CMD_READ_CHARGER_DATA, slot)
            response = self.read()
            if response[-1] != self.packet_checksum(response):
                continue

            # CMD_OPCODE = response[0]
            data = unpack(CHARGE_DATA_STRUCT, response)
            battery = Battery(*data)
            battery = battery._replace(type=BATTERY_TYPE[battery.type])
            battery = battery._replace(mode=BATTERY_MODE[battery.mode])
            battery = battery._replace(cycle_mode=CYCLE_MODE[battery.cycle_mode])
            battery = battery._replace(tem_unit=TEM_UNIT[battery.tem_unit])
            batteries.append(battery)
        return batteries

    def get_charging_progress(self, battery_slot='all'):
        """Get the current slot status.

        The parameter *battery_slot* accepts the value ``'all'`` and a list of *integers*. These
        *interger* represents the `slot` the charger provides. The index starts at `0`. The value
        ``'all'`` is identical with ``[0, 1, 2, 3]`` as value for `battery_slot`.

        :param battery_slot: Battery slots to query
        :type battery_slot: literal ``'all'`` or a *list* with slot indeces.
        :rtype: list of :data:`ProgressInfo`
        """
        batteries = []

        # All slots
        if battery_slot == 'all':
            battery_slot = range(4)
        else:
            battery_slot = [battery_slot]

        for slot in battery_slot:
            self.send(CMD_READ_PROGRESS_DATA, slot)
            response = self.read()
            if response[-1] != self.packet_checksum(response):
                continue

            """
            #: TODO resolve unknown values
            num4 = response[3]
            num5 = response[4]
            print('num3  {}'.format(num3))
            print('num4  {}'.format(num4))
            print('num5  {}'.format(num5))
            print('num6  {}'.format(num6))

            # num6 might by use to detect overflows in work mode
            work = response[5]
            num6 = 0
            #: TODO find out what *num6* is for
            if work >= 128:
                num6 = work - 128 + 1
            """

            data = unpack(PROGRESS_STATUS_STRUCT, response)
            pinfo = ProgressInfo(*data, 0)
            if pinfo.work == 2:
                pinfo = pinfo._replace(dcaps=pinfo.caps)
            if pinfo.work_time > 0:
                pinfo = pinfo._replace(work_time=pinfo.work_time - 1)
            pinfo = pinfo._replace(bat_tem=pinfo.bat_tem & 0x7fff)
            batteries.append(pinfo)
        return batteries

    def send_raw(self, buffer):
        """Send *buffer* to the device.

        This function is used to send *buffer* as raw packet to the device. This function can be
        used to send constant commands like in :func:`start`.

        :param buffer: Packet send to the device
        :type buffer: bytes
        :returns: Number of bytes send
        :rtype: int
        """
        return self.device.write(self.ep_out.bEndpointAddress, buffer)

    def send(self, cmd, buffer):
        """Send a command with *buffer* as payload to the device.

        This function is used to send *buffer* as raw packet to the device. This function can be
        used to send constant commands like in :func:`start`.

        :param cmd: Command opcode
        :type cmd: byte
        :param buffer: Packet payload
        :type buffer: byte
        :rtype: None
        """
        if cmd == CMD_READ_CHARGER_DATA:
            slotcmd = (int.from_bytes(cmd, byteorder='little')) + buffer
            cmd_packet = pack('2scxbb2s', CMD_PACKET_HEADER, cmd, buffer, slotcmd, CMD_PACKET_TAIL)
            self.send_raw(cmd_packet)
        elif cmd == CMD_READ_PROGRESS_DATA:
            slotcmd = (int.from_bytes(cmd, byteorder='little')) + buffer
            cmd_packet = pack('2scxbb2s', CMD_PACKET_HEADER, cmd, buffer, slotcmd, CMD_PACKET_TAIL)
            self.send_raw(cmd_packet)

    def read(self, expected_length=64):
        """Read a response of *expected_length* from the device.

        After sending a packet to the device, the device will answer.

        :param expected_length: Length of data to read
        :type expected_length: int
        :returns: Packet with the response
        :rtype: bytes
        """
        return self.device.read(self.ep_in.bEndpointAddress, expected_length).tobytes()


if __name__ == '__main__':
    mc3000 = MC3000()
    info = mc3000.get_machine_info()._asdict()
    batteries = {
        battery.slot + 1: battery._asdict() for battery in mc3000.get_battery_data()
    }
    status = {
        charge.slot + 1: charge._asdict() for charge in mc3000.get_charging_progress()
    }

    print(json.dumps({
        'info': info,
        'batteries': batteries,
        'status': status
    }))
