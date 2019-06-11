from __future__ import print_function, division
__version__ = '0.0.1'
import datetime as dt
import logging
import os.path
from threading import Thread, RLock

from zeep.client import Client, CachingClient, Settings
from zeep.wsse.username import UsernameToken
import zeep.helpers

from onvif.exceptions import ONVIFError
from onvif.definition import SERVICES

logger = logging.getLogger('onvif')
logging.basicConfig(level=logging.INFO)
logging.getLogger('zeep.client').setLevel(logging.CRITICAL)


# Ensure methods to raise an ONVIFError Exception
# when some thing was wrong
def safe_func(func):
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as err:
            raise ONVIFError(err)
    return wrapped


class UsernameDigestTokenDtDiff(UsernameToken):
    """
    UsernameDigestToken class, with a time offset parameter that can be adjusted;
    This allows authentication on cameras without being time synchronized.
    Please note that using NTP on both end is the recommended solution,
    this should only be used in "safe" environments.
    """
    def __init__(self, user, passw, dt_diff=None, **kwargs):
        super().__init__(user, passw, **kwargs)
        self.dt_diff = dt_diff  # Date/time difference in datetime.timedelta

    def apply(self, envelope, headers):
        old_created = self.created
        if self.created is None:
            self.created = dt.datetime.utcnow()
        if self.dt_diff is not None:
            self.created += self.dt_diff
        result = super().apply(envelope, headers)
        self.created = old_created
        return result


class ONVIFService(object):
    """
    Python Implemention for ONVIF Service.
    Services List:
        DeviceMgmt DeviceIO Event AnalyticsDevice Display Imaging Media
        PTZ Receiver RemoteDiscovery Recording Replay Search Extension

    >>> from onvif import ONVIFService
    >>> device_service = ONVIFService('http://192.168.0.112/onvif/device_service',
    ...                           'admin', 'foscam',
    ...                           '/etc/onvif/wsdl/devicemgmt.wsdl')
    >>> ret = device_service.GetHostname()
    >>> print ret.FromDHCP
    >>> print ret.Name
    >>> device_service.SetHostname(dict(Name='newhostname'))
    >>> ret = device_service.GetSystemDateAndTime()
    >>> print ret.DaylightSavings
    >>> print ret.TimeZone
    >>> dict_ret = device_service.to_dict(ret)
    >>> print dict_ret['TimeZone']

    There are two ways to pass parameter to services methods
    1. Dict
        params = {'Name': 'NewHostName'}
        device_service.SetHostname(params)
    2. Type Instance
        params = device_service.create_type('SetHostname')
        params.Hostname = 'NewHostName'
        device_service.SetHostname(params)
    """

    @safe_func
    def __init__(self, xaddr, user, passwd, url,
                 encrypt=True, daemon=False, zeep_client=None, no_cache=False,
                 dt_diff=None, binding_name='', transport=None):
        if not os.path.isfile(url):
            raise ONVIFError('%s doesn`t exist!' % url)

        self.url = url
        self.xaddr = xaddr
        wsse = UsernameDigestTokenDtDiff(user, passwd, dt_diff=dt_diff, use_digest=encrypt)
        # Create soap client
        if not zeep_client:
            ClientType = Client if no_cache else CachingClient
            settings = Settings()
            settings.strict = False
            settings.xml_huge_tree = True
            self.zeep_client = ClientType(wsdl=url, wsse=wsse, transport=transport, settings=settings)
        else:
            self.zeep_client = zeep_client
        self.ws_client = self.zeep_client.create_service(binding_name, self.xaddr)

        # Set soap header for authentication
        self.user = user
        self.passwd = passwd
        # Indicate wether password digest is needed
        self.encrypt = encrypt
        self.daemon = daemon
        self.dt_diff = dt_diff
        self.create_type = lambda x: self.zeep_client.get_element('ns0:' + x)()

    @classmethod
    @safe_func
    def clone(cls, service, *args, **kwargs):
        clone_service = service.ws_client.clone()
        kwargs['ws_client'] = clone_service
        return ONVIFService(*args, **kwargs)

    @staticmethod
    @safe_func
    def to_dict(zeepobject):
        # Convert a WSDL Type instance into a dictionary
        return {} if zeepobject is None else zeep.helpers.serialize_object(zeepobject)

    def service_wrapper(self, func):
        @safe_func
        def wrapped(params=None, callback=None):
            def call(params=None, callback=None):
                # No params
                # print(params.__class__.__mro__)
                if params is None:
                    params = {}
                else:
                    params = ONVIFService.to_dict(params)
                try:
                    ret = func(**params)
                except TypeError:
                    ret = func(params)
                if callable(callback):
                    callback(ret)
                return ret

            if self.daemon:
                th = Thread(target=call, args=(params, callback))
                th.daemon = True
                th.start()
            else:
                return call(params, callback)
        return wrapped

    def __getattr__(self, name):
        """
        Call the real onvif Service operations,
        See the official wsdl definition for the
        APIs detail(API name, request parameters,
        response parameters, parameter types, etc...)
        """
        builtin = name.startswith('__') and name.endswith('__')
        if builtin:
            return self.__dict__[name]
        else:
            return self.service_wrapper(getattr(self.ws_client, name))


class ONVIFCamera(object):
    """
    Python Implementation of an ONVIF compliant device.
    This class integrates ONVIF services

    adjust_time parameter allows authentication on cameras without being time synchronized.
    Please note that using NTP on both end is the recommended solution,
    this should only be used in "safe" environments.
    Also, this cannot be used on AXIS camera, as every request is authenticated, contrary to ONVIF standard

    >>> from onvif import ONVIFCamera
    >>> mycam = ONVIFCamera('192.168.0.112', 80, 'admin', '12345')
    >>> mycam.devicemgmt.GetServices(False)
    >>> media_service = mycam.create_media_service()
    >>> ptz_service = mycam.create_ptz_service()
    # Get PTZ Configuration:
    >>> ptz_service.GetConfiguration()
    """

    # Class-level variables
    services_template = {'devicemgmt': None, 'ptz': None, 'media': None,
                         'imaging': None, 'events': None, 'analytics': None}
    use_services_template = {'devicemgmt': True, 'ptz': True, 'media': True,
                             'imaging': True, 'events': True, 'analytics': True}

    def __init__(self, host, port, user, passwd,
                 wsdl_dir=os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                       "wsdl"),
                 encrypt=True, daemon=False, no_cache=False, adjust_time=False,
                 transport=None):
        os.environ.pop('http_proxy', None)
        os.environ.pop('https_proxy', None)
        self.host = host
        self.port = int(port)
        self.user = user
        self.passwd = passwd
        self.wsdl_dir = wsdl_dir
        self.encrypt = encrypt
        self.daemon = daemon
        self.no_cache = no_cache
        self.adjust_time = adjust_time
        self.transport = transport

        # Active service client container
        self.services = {}
        self.services_lock = RLock()

        # Set xaddrs
        self.update_xaddrs()

        self.to_dict = ONVIFService.to_dict

    def update_xaddrs(self):
        # Establish devicemgmt service first
        self.dt_diff = None
        self.devicemgmt = self.create_devicemgmt_service()
        if self.adjust_time:
            cdate = self.devicemgmt.GetSystemDateAndTime().UTCDateTime
            cam_date = dt.datetime(cdate.Date.Year, cdate.Date.Month, cdate.Date.Day,
                                   cdate.Time.Hour, cdate.Time.Minute, cdate.Time.Second)
            self.dt_diff = cam_date - dt.datetime.utcnow()
            self.devicemgmt.dt_diff = self.dt_diff
            self.devicemgmt = self.create_devicemgmt_service()
        # Get XAddr of services on the device
        self.xaddrs = {}
        capabilities = self.devicemgmt.GetCapabilities({'Category': 'All'})
        for name in capabilities:
            try:
                retrived_address=capabilities[name].XAddr
                right=retrived_address.split("//")[1]
                retrived_url=right.split("/")[0]
                ip_address=retrived_url.split(":")[0]
                port_address = retrived_url.split(":")[1]
                if (self.host != ip_address or self.port != port_address):
                    remaining=right.split("/")[1]
                    new_address="http://"+self.host+":"+str(self.port)+"/"+right.split("/")[1]+"/"+right.split("/")[2]
                    capabilities[name].XAddr=new_address
            except:
                pass
            capability = capabilities[name]
            try:
                if name.lower() in SERVICES and capability is not None:
                    ns = SERVICES[name.lower()]['ns']
                    self.xaddrs[ns] = capability['XAddr']
            except Exception:
                logger.exception('Unexpected service type')

        with self.services_lock:
            try:
                self.event = self.create_events_service()
                self.xaddrs['http://www.onvif.org/ver10/events/wsdl/PullPointSubscription'] = \
                    self.event.CreatePullPointSubscription().SubscriptionReference.Address._value_1
            except Exception:
                pass

    def update_url(self, host=None, port=None):
        changed = False
        if host and self.host != host:
            changed = True
            self.host = host
        if port and self.port != port:
            changed = True
            self.port = port

        if not changed:
            return

        self.devicemgmt = self.create_devicemgmt_service()
        self.capabilities = self.devicemgmt.GetCapabilities()

        with self.services_lock:
            for sname in self.services.keys():
                xaddr = getattr(self.capabilities, sname.capitalize).XAddr
                self.services[sname].ws_client.set_options(location=xaddr)

    def get_service(self, name, create=True):
        service = getattr(self, name.lower(), None)
        if not service and create:
            return getattr(self, 'create_%s_service' % name.lower())()
        return service

    def get_definition(self, name, portType=None):
        """Returns xaddr and wsdl of specified service"""
        # Check if the service is supported
        if name not in SERVICES:
            raise ONVIFError('Unknown service %s' % name)
        wsdl_file = SERVICES[name]['wsdl']
        ns = SERVICES[name]['ns']

        binding_name = '{%s}%s' % (ns, SERVICES[name]['binding'])

        if portType:
            ns += '/' + portType

        wsdlpath = os.path.join(self.wsdl_dir, wsdl_file)
        if not os.path.isfile(wsdlpath):
            raise ONVIFError('No such file: %s' % wsdlpath)

        # XAddr for devicemgmt is fixed:
        if name == 'devicemgmt':
            xaddr = '%s:%s/onvif/device_service' % \
                    (self.host if (self.host.startswith('http://') or self.host.startswith('https://'))
                     else 'http://%s' % self.host, self.port)
            return xaddr, wsdlpath, binding_name

        # Get other XAddr
        xaddr = self.xaddrs.get(ns)
        if not xaddr:
            raise ONVIFError("Device doesn't support service: %s" % name)

        return xaddr, wsdlpath, binding_name

    def create_onvif_service(self, name, portType=None, transport=None):
        """
        Create ONVIF service client.

        :param name: service name, should be present as a key within
        the `SERVICES` dictionary declared within the `onvif.definition` module
        :param portType:
        :param transport:
        :return:
        """
        """Create ONVIF service client"""

        name = name.lower()
        xaddr, wsdl_file, binding_name = self.get_definition(name, portType)

        with self.services_lock:
            if not transport:
                transport = self.transport

            service = ONVIFService(xaddr, self.user, self.passwd,
                                   wsdl_file, self.encrypt,
                                   self.daemon, no_cache=self.no_cache,
                                   dt_diff=self.dt_diff,
                                   binding_name=binding_name,
                                   transport=transport)

            self.services[name] = service

            setattr(self, name, service)
            if not self.services_template.get(name):
                self.services_template[name] = service

        return service

    def create_devicemgmt_service(self, transport=None):
        # The entry point for devicemgmt service is fixed.
        return self.create_onvif_service('devicemgmt', transport=transport)

    def create_media_service(self, transport=None):
        return self.create_onvif_service('media', transport=transport)

    def create_ptz_service(self, transport=None):
        return self.create_onvif_service('ptz', transport=transport)

    def create_imaging_service(self, transport=None):
        return self.create_onvif_service('imaging', transport=transport)

    def create_deviceio_service(self, transport=None):
        return self.create_onvif_service('deviceio', transport=transport)

    def create_events_service(self, transport=None):
        return self.create_onvif_service('events', transport=transport)

    def create_analytics_service(self, transport=None):
        return self.create_onvif_service('analytics', transport=transport)

    def create_recording_service(self, transport=None):
        return self.create_onvif_service('recording', transport=transport)

    def create_search_service(self, transport=None):
        return self.create_onvif_service('search', transport=transport)

    def create_replay_service(self, transport=None):
        return self.create_onvif_service('replay', transport=transport)

    def create_pullpoint_service(self, transport=None):
        return self.create_onvif_service('pullpoint',
                                         portType='PullPointSubscription',
                                         transport=transport)

    def create_receiver_service(self, transport=None):
        return self.create_onvif_service('receiver', transport=transport)

    def create_notification_service(self, transport=None):
        return self.create_onvif_service('notification', transport=transport)

    def create_subscription_service(self, transport=None):
        return self.create_onvif_service('subscription', transport=transport)
