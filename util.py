from django.conf import settings
from django.http import HttpResponse, Http404
from django.contrib.auth.decorators import login_required
import os, mapnik
from copy import deepcopy
from ogcserver.configparser import SafeConfigParser
from ogcserver.WMS import BaseWMSFactory
from ogcserver.wms111 import ServiceHandler as ServiceHandler111
from ogcserver.wms130 import ServiceHandler as ServiceHandler130
from ogcserver.exceptions import OGCException, ServerConfigurationError

base_path, tail = os.path.split(__file__)

modis_srs = "+proj=sinu +R=6371007.181 +nadgrids=@null +wktext"
modis_srs = "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +a=6371007.181 +b=6371007.181 +units=m +no_defs"
merc_srs  = "+init=epsg:3857"
stand_srs = "+init=epsg:4326"

#Monkey patch to enable WMS standard handling of variable bbox/res ratio
from StringIO import StringIO
from mapnik import Image, render
from ogcserver.common import PIL_TYPE_MAPPING, Response

def newGetMap(self, params):
    # HACK: check if the image should be strechted
    bbox_ratio = float(params['bbox'][2] - params['bbox'][0]) / float(params['bbox'][3] - params['bbox'][1])
    image_ratio = float(params['width']) / float(params['height'])
    img_height = params['height']
    resize = False
    
    if int(bbox_ratio * 100) != int(image_ratio * 100):
        params['height'] = int(params['height'] / bbox_ratio)
        resize = True
    
    m = self._buildMap(params)
    im = Image(params['width'], params['height'])
    render(m, im)
    format = PIL_TYPE_MAPPING[params['format']]
    
    if resize:
        import Image as PILImage
        size = params['width'], params['height']
        im = PILImage.open(StringIO(im.tostring(format)))
        size = params['width'], img_height
        im = im.resize(size)
        output = StringIO()
        im.save(output, format=format)
        return Response(params['format'].replace('8',''), output.getvalue())
        
    return Response(params['format'].replace('8',''), im.tostring(format))

import ogcserver.common
patched = ogcserver.common.WMSBaseServiceHandler
patched.GetMap = newGetMap
ogcserver.common.WMSBaseServiceHandler = patched


def ogc_response(request, mapfactory):
    
    conf = SafeConfigParser()
    conf.readfp(open(base_path+"/ogcserver.conf"))
    
    reqparams = lowerparams(request.GET)
    if 'srs' in reqparams:
        reqparams['srs'] = str(reqparams['srs'])
    if 'styles' not in reqparams:
        reqparams['styles'] = ''

    onlineresource = 'http://%s%s?' % (request.META['HTTP_HOST'], request.META['PATH_INFO'])

    if not reqparams.has_key('request'):
        raise OGCException('Missing request parameter.')
    req = reqparams['request']
    del reqparams['request']
    if req == 'GetCapabilities' and not reqparams.has_key('service'):
        raise OGCException('Missing service parameter.')
    if req in ['GetMap', 'GetFeatureInfo']:
        service = 'WMS'
    else:
        service = reqparams['service']
    if reqparams.has_key('service'):
        del reqparams['service']
    try:
        ogcserver = __import__('ogcserver.' + service)
    except:
        raise OGCException('Unsupported service "%s".' % service)
    ServiceHandlerFactory = getattr(ogcserver, service).ServiceHandlerFactory
    servicehandler = ServiceHandlerFactory(conf, mapfactory, onlineresource, reqparams.get('version', None))
    if reqparams.has_key('version'):
        del reqparams['version']
    if req not in servicehandler.SERVICE_PARAMS.keys():
        raise OGCException('Operation "%s" not supported.' % request, 'OperationNotSupported')
    ogcparams = servicehandler.processParameters(req, reqparams)
    try:
        requesthandler = getattr(servicehandler, req)
    except:
        raise OGCException('Operation "%s" not supported.' % req, 'OperationNotSupported')

    # stick the user agent in the request params
    # so that we can add ugly hacks for specific buggy clients
    ogcparams['HTTP_USER_AGENT'] = request.META['HTTP_USER_AGENT']

    wms_resp = requesthandler(ogcparams)    

    response = HttpResponse()
    response['Content-length'] = str(len(wms_resp.content))
    response['Content-Type'] = wms_resp.content_type
    response.write(wms_resp.content)
        
    return response

def lowerparams(params):
    reqparams = {}
    for key, value in params.items():
        reqparams[key.lower()] = value
    return reqparams

