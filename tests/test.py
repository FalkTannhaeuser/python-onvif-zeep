#!/usr/bin/python
# -*-coding=utf-8
from __future__ import print_function, division
import unittest

from onvif import ONVIFCamera, ONVIFError

CAM_HOST = '172.20.9.84'
CAM_PORT = 80
CAM_USER = 'root'
CAM_PASS = 'password'

DEBUG = False


def log(ret):
    if DEBUG:
        print(ret)


class TestDevice(unittest.TestCase):

    # Class level cam. Run this test more efficiently..
    cam = ONVIFCamera(CAM_HOST, CAM_PORT, CAM_USER, CAM_PASS)

    # ***************** Test Capabilities ***************************
    def test_GetWsdlUrl(self):
        self.cam.devicemgmt.GetWsdlUrl()

    def test_GetServices(self):
        """
        Returns a collection of the devices
        services and possibly their available capabilities
        """
        params = {'IncludeCapability': True}
        self.cam.devicemgmt.GetServices(params)
        params = self.cam.devicemgmt.create_type('GetServices')
        params.IncludeCapability = False
        self.cam.devicemgmt.GetServices(params)

    def test_GetServiceCapabilities(self):
        """Returns the capabilities of the device service."""
        self.cam.devicemgmt.GetServiceCapabilities()

    def test_GetCapabilities(self):
        """
        Provides a backward compatible interface for the base capabilities.
        """
        categories = ['PTZ', 'Media', 'Imaging',
                      'Device', 'Analytics', 'Events']
        self.cam.devicemgmt.GetCapabilities()
        for category in categories:
            self.cam.devicemgmt.GetCapabilities({'Category': category})

        with self.assertRaises(ONVIFError):
            self.cam.devicemgmt.GetCapabilities({'Category': 'unknown'})

    # *************** Test Network *********************************
    def test_GetHostname(self):
        """ Get the hostname from a device """
        self.cam.devicemgmt.GetHostname()

    def test_SetHostname(self):
        """
        Set the hostname on a device
        A device shall accept strings formatted according to
        RFC 1123 section 2.1 or alternatively to RFC 952,
        other string shall be considered as invalid strings
        """
        pre_host_name = self.cam.devicemgmt.GetHostname()

        self.cam.devicemgmt.SetHostname({'Name': 'testHostName'})
        self.assertEqual(self.cam.devicemgmt.GetHostname().Name, 'testHostName')
        self.cam.devicemgmt.SetHostname({'Name': pre_host_name.Name})

    def test_SetHostnameFromDHCP(self):
        """ Controls whether the hostname shall be retrieved from DHCP """
        ret = self.cam.devicemgmt.SetHostnameFromDHCP(dict(FromDHCP=False))
        self.assertTrue(isinstance(ret, bool))

    def test_GetDNS(self):
        """ Gets the DNS setting from a device """
        ret = self.cam.devicemgmt.GetDNS()
        self.assertTrue(hasattr(ret, 'FromDHCP'))
        if not ret.FromDHCP and len(ret.DNSManual) > 0:
            log(ret.DNSManual[0].Type)
            log(ret.DNSManual[0].IPv4Address)

    def test_SetDNS(self):
        """ Set the DNS settings on a device """
        self.cam.devicemgmt.SetDNS(dict(FromDHCP=False))

    def test_GetNTP(self):
        """ Get the NTP settings from a device """
        ret = self.cam.devicemgmt.GetNTP()
        if not ret.FromDHCP:
            self.assertTrue(hasattr(ret, 'NTPManual'))
            log(ret.NTPManual)

    def test_SetNTP(self):
        """Set the NTP setting"""
        self.cam.devicemgmt.SetNTP(dict(FromDHCP=False))

    def test_GetDynamicDNS(self):
        """Get the dynamic DNS setting"""
        ret = self.cam.devicemgmt.GetDynamicDNS()
        log(ret)

    def test_SetDynamicDNS(self):
        """ Set the dynamic DNS settings on a device """
        self.cam.devicemgmt.GetDynamicDNS()
        self.cam.devicemgmt.SetDynamicDNS({'Type': 'NoUpdate', 'Name': None,
                                           'TTL': None})


if __name__ == '__main__':
    unittest.main()
