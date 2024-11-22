import asyncio
import binascii
import hashlib
import json
import struct
import sys
import os
import ssl

# 判断是否为micropython的标志位
ISMICROPYTHON=True if sys.implementation.name=='micropython' else False

SERVER_FULLNAME='Multi-Task Asyncio Server'
SERVER_NAME='MTAS'
VERSION='1.0'
SERVER=SERVER_NAME+VERSION
SERVER_PORT=8888

HTTP_METHODS=['GET','PUT','POST','HEAD']

#WEBSOCKET连接相关的处理
MAGIC_STR='258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
WEBSOCKET_RESPONSE='HTTP/1.1 101 Switching Protocols\r\n'+ \
           f'Server: {SERVER}\r\n' + \
           'Upgrade: websocket\r\n' + \
           'Connection: Upgrade\r\n' + \
           'Sec-WebSocket-Accept: {socketkey}\r\n' + \
           'Sec-WebSocket-Version: 13\r\n\r\n'

URL_ERROR_HTML='''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" 
content="width=device-width, initial-scale=1.0"><title>404 Not Found</title>
<style>body {font-family: 'Arial', sans-serif;background-color: #f8f8f8;text-align: center;padding: 50px;}
h1 {color: #333;}p {color: #666;}</style></head><body><h1>404 Not Found</h1><p>The requested URL was not 
found on this server.</p></body></html>'''


###############################################################################
#JSON RPC2.0
#协议概述：https://zhuanlan.zhihu.com/p/44096204
#协议标准：https://www.jsonrpc.org/specification
#请求和响应格式
#--> {"method": "add", "id": "asdf", "jsonrpc": "2.0", "params": [3, 4]}
#成功<-- {"jsonrpc": "2.0", "id": "asdf", "result": "33"}
#失败<-- {"jsonrpc": "2.0", "id": "asdf", "error": {"code": -32603, "message": "internel error", "data": "error data"}}

class Jsonrpc:
    #实现了jsonrpc协议请求的解析和响应的构造
    def __init__(self,request={},response={}) :
        self.request=request 
        self.response=response
        self.id=request.get('id',None)
        self.method=request.get('method',None)
        self.protocol=request.get('jsonrpc','2.0')
        self.params=request.get('params',None)

    @staticmethod
    def parserequest(reqtxtorbytes):
        try:
            req=json.loads(reqtxtorbytes)
        except Exception:
            return Jsonrpc().error(-32700,'Parse error','Invalid JSON was received by the server. An error occurred on the server while parsing the JSON text.')
        if req.get('jsonrpc','')=='2.0' and 'method' in req and req.get('id','')!='':
            #是正确的JsonRPC请求
            if 'params' in req:
                if isinstance(req['params'],(list,tuple,dict,str)):
                    return Jsonrpc(req)
                else:
                    return Jsonrpc(req).error(-32602,'Invalid params','Invalid method parameter(s).')
            else:
                return Jsonrpc(req)
        return Jsonrpc(req).error(-32600,'Invalid Request','The JSON sent is not a valid Request object.')
    
    def success(self,result):
        # result能够被json化，是列表或字符串，或者字典
        # 直接返回编码的二进制
        rsp={'jsonrpc':self.protocol,'id':self.id}
        rsp['result']=result
        return json.dumps(rsp).encode()

    def error(self,code=-32603,message='Internal error',data='Internal JSON-RPC error.'):
        '''  code	 message	 meaning
            -32700	Parse error	Invalid JSON was received by the server.An error occurred on the server while parsing the JSON text.
            -32600	Invalid Request	The JSON sent is not a valid Request object.
            -32601	Method not found	The method does not exist / is not available.
            -32602	Invalid params	Invalid method parameter(s).
            -32603	Internal error	Internal JSON-RPC error.
            -32000 to -32099	Server error	Reserved for implementation-defined server-errors.
        '''
        rsp={'jsonrpc':self.protocol,'id':self.id}
        rsp['error']=dict(code=code,message=message,data=data)
        return json.dumps(rsp).encode()

    @staticmethod
    def makerequest(method,params=None,id=None,protocol='2.0'):
        req=dict(method=method,id=id,jsonrpc=protocol)
        if params:
            req['params']=params
        return json.dumps(req).encode()
    
    @staticmethod
    def parseresponse(rpcresponse):
        try:
            rsp=json.loads(rpcresponse)
        except Exception:
            return None
        if 'id' in rsp and 'jsonrpc' in rsp:
            return rsp
        return None


###############################################################################
#MTAS-SOCKET 应用管理器
class Mtassocketapp():
    def __init__(self):
        self.funcs={}
    def addfunc(self,url='/', method='publisher', callback=lambda x:x):
        self.funcs[(url,method.upper())]=callback
    def removefunc(self,url='/', method='publisher'):
        if (url,method.upper()) in self.funcs:
            del self.funcs[(url, method)]
    def getfunc(self,url='/', method='publisher'):
        return self.funcs.get((url, method.upper()), None)

    def route(self, url, method ):
        """
        装饰器用于添中（url，method，和回调函数）
        """
        def wrapper(handler):
            self.addfunc(url,method, handler)
            return handler
        return wrapper

def skroute(url,method='publisher'):     
    #装饰器，用于添加MTAS-Socket服务的路由
    global mtassocketapp
    return mtassocketapp.route(url,method)


#MTAS-SOCKET连接处理器
class MtassocketHandler:
    METHODS=['PUBLISHER', 'SUBSCRIBER', 'SERVER', 'CLIENT', 'RAWPUB']  #RAWPUB用于发布纯文本或二进制消息，类似于中继
    FRAME_TYPE=['text','bin']
    def __init__(self, reader, writer, app):
        self.env={}
        self.app=app
        self.reader=reader
        self.writer=writer

    async def write(self,data:bytes):
        self.writer.write(data)
        await self.writer.drain()
        
    async def run(self,request_env):
        self.env=request_env
        print(f'mtassocket connection has established from {self.env["client_ip"]}')
        path=self.env["PATH_INFO"]
        method=self.env["REQUEST_METHOD"]
        callback=self.app.getfunc(path,method)
        if method=='PUBLISHER':   
            while True:
                res,tp=await callback(self.env)
                frame=self.makeframe(res,tp)
                await self.write(frame)
        if method=='SUBSCRIBER':  
            while True:
                data=await self.readframe()
                if len(data):
                    await callback(self.env,data)
        if method=='SERVER':
            while True:
                data=await self.readframe()
                if len(data):
                    res,tp=await callback(self.env,data)
                    frame=self.makeframe(res,tp)
                    await self.write(frame)
        if method=='CLIENT':
            while True:
                res,tp= await callback(self.env)
                frame=self.makeframe(res,tp)
                await self.write(frame)
                data=await self.readframe()
                await callback(self.env,data)
        if method=='RAWPUB':
            while True:
                res,tp=await callback(self.env)
                if res:
                    await self.write(res)
        raise Exception('mtassocket pattern error')

    def makeframe(self,data:bytes=b'{}',type='text'):    
        #生成数据帧，数据帧由3部分构成：负载长度（payload length）+数据类型+数据
        #负载长度为8个字节，表示数据部分的长度，使用填充0的ascii码表示，如数据长度为1024时，表示为b'00001024'
        #数据类型是1个字节，ascii码为b'1'时表示bin(二进制类型)，ascii码为b'0'时表示文本类型
        #data是bytes类型，对于文本需要在传入前调用encode()方法编码
        #type是'text'或'bin'
        datalength=len(data)  #计算数据长度
        typecode=1 if type=='text' else 0
        lendatastr=f'{datalength:08}{typecode}'
        frame = lendatastr.encode()
        return frame+data

    async def readframe(self):
        #从客户端读取完整的一帧数据,数据帧结构应当与上述发送的一致
        frame_meta=await self.reader.readexactly(9)
        if not frame_meta.isdigit(): 
            raise Exception('mtassockete frame meta error')
        datalen=int(frame_meta[:8])
        typecode=frame_meta[-1]  #字节转为了0-255的数字了
        buffer = bytearray() 
        curpos=0
        while datalen-curpos>0:
            buffer.extend(await self.reader.read(datalen-curpos))
            curpos=len(buffer)
        if typecode==48: # 48==b'0': #如果是bin
            return buffer
        if typecode==49: #b'1': #如果是text
            return buffer.decode()
        else:
            raise Exception(f'mtassockete typecode error! typecode:{typecode.encode()}')

###############################################################################
#Websocket的部分
class Websocketapp:
    def __init__(self):
        self.funcs={}
    def addfunc(self, url='/', method='publisher', callback=lambda x:x):
        self.funcs[url]=[callback, method.upper()]

    def removefunc(self, url='/'):
        if url in self.funcs:
            del self.funcs[url]

    def getfunc(self, path):
        return self.funcs.get(path,(None, None))

    def route(self, url, method):
        def wrapper(handler):
            self.addfunc(url, method, handler)
            return handler
        return wrapper

def wsroute(url, method='publisher'):
    #装饰器，用于添加WEBSOCKET服务的路由
    global websocketapp
    return websocketapp.route(url, method)   

class WebsocketHandler:
    #每一个Websocket请求需要产生一个Handler进行服务（处理）
    #https://zhuanlan.zhihu.com/p/407711596
    #https://datatracker.ietf.org/doc/html/rfc6455
    METHODS=['PUBLISHER', 'SUBSCRIBER', 'SERVER', 'CLIENT']
    FRAME_TYPE=['text','bin','ping','pong']
    def __init__(self,reader,writer,app):
        self.env={}
        self.app=app
        self.isfirstconnection=True #用于建立连接时的握手阶段
        self.reader=reader
        self.writer=writer
    
    async def write(self,data:bytes):
        self.writer.write(data)
        await self.writer.drain()
        
    async def run(self,request_env):
        self.env=request_env
        #首次连接进行握手
        await self.dowebsockethandshake()
        print(f'websocket connection has established from {self.env["client_ip"]}')
        path=self.env["PATH_INFO"]
        callback,method=self.app.getfunc(path)
        if method=='PUBLISHER':
            while True:
                res,tp=await callback(self.env)
                frame=self.makeframe(res,tp)
                await self.write(frame)
        if method=='SUBSCRIBER': 
            while True:
                data=await self.readframe()
                if len(data):
                    await callback(self.env,data)
        if method=='SERVER':
            while True:
                data=await self.readframe()
                if len(data):
                    res,tp=await callback(self.env,data)
                    frame=self.makeframe(res,tp)
                    await self.write(frame)
        if method=='CLIENT':
            while True:
                res,tp= await callback(self.env) #发起请求
                frame=self.makeframe(res,tp)
                await self.write(frame)
                data=await self.readframe()
                await callback(self.env,data) #处理响应

    async def dowebsockethandshake(self):
        #处理websocket首次连接时的握手，与客户端建立持久链接
        headers=self.env['request_headers']
        code=headers['Sec-WebSocket-Key']+MAGIC_STR
        code=hashlib.sha1(code.encode()).digest()
        code=binascii.b2a_base64(code,newline=False).decode()
        response=WEBSOCKET_RESPONSE.format(socketkey=code)
        await self.write(response.encode())      
        self.isfirstconnection=False
        return True
        
    def makeframe(self,data:bytes=b'ping',frametype:str='text'): 
        #目前只支持将所有数据打包为一个数据帧，后续是否要考虑分帧情况？似乎没有必要，因为最大帧长为2^64次方已经足够大
        #但是要考虑最大帧是否超出缓存
        #生成一个websocket数据包
        if frametype=='ping':
            typestr='89'
            data=b'ping'    
        elif frametype=='pong':
            typestr='8A'
            data=b'pong'
        #type=0x1, 代表当前是一个 text frame ;0x2, 代表当前是一个 binary frame
        elif frametype=='text':#81是0x81是16进制10000001 看websocket数据帧格式
            typestr='81'
        elif frametype=='bin':
            typestr='82'
        else:
            #type=='close': 如何处理close事件？现在直接通过协程异常退出
            typestr='88'   
            data=b'close'
        datalength=len(data)       #表示有多少个字节
        framehead=bytes([int(typestr,16)])   #十六进制字符串 typestr 转换为一个整数，然后将该整数强制转换为一个字节（bytes对象），并将其赋值给 framehead。
        #print(f"web socket {self.env['path']} data length is:",len(data))

        #数据长度<=125是7位标志，126是16位标志，127是64位标志
        if datalength<126:
            framehead+=bytes([datalength])     
        elif datalength<65536: #2**16:
            framehead+=bytes([126])+struct.pack('!H',datalength)  #如果 datalength 大于等于 126 且小于 2^16（65536），那么数据长度用两个字节表示，并在 framehead 后面追加一个字节的标志（126）
        else:                        #将数据长度打包成两个字节的网络字节顺序（big-endian）表示
            framehead+=bytes([127])+struct.pack('!Q',datalength)  #如果 datalength 大于等于 2^16，那么数据长度用八个字节表示，并在 framehead 后面追加一个字节的标志（127）
        return framehead+data

    async def readframe(self):
        #从客户端读取完整的一帧数据
        data=bytearray()
        isfinish=True
        while True:
            tmpdata=b''
            res=await self.reader.read(2)
            isfinish=bool(res[0] & 0x80)
            opcode=res[0] & 0x0f
            msk=bool(res[1] & 0x80)
            if not msk:
                raise Exception('mask error')
            payloadlen=res[1] & 0x7f
            if payloadlen<126:
                mask=await self.reader.read(4)
                tmpdata+=await self.reader.read(payloadlen)
            elif payloadlen==126:
                blen=await self.reader.read(2)
                payloadlen=struct.unpack('!H',blen)[0]
                mask=await self.reader.read(4)
                curpos=0
                while payloadlen-curpos>0:
                    tmpdata+=await self.reader.read(payloadlen-curpos)
                    curpos=len(tmpdata)
            else: #payloadlen==127
                blen=await self.reader.read(8)
                payloadlen=struct.unpack('!Q',blen)[0]
                mask=await self.reader.read(4)
                curpos=0
                while payloadlen-curpos>0:
                    tmpdata+=await self.reader.read(payloadlen-curpos)
                    curpos=len(tmpdata)
            for idx, bt in enumerate(tmpdata):
                data.append(bt ^ mask[idx%4])   #异或操作解码，相同为0，不同为1
            if isfinish: break
        if opcode==0xa: #如果是ping
            frame=self.makeframe(b'pong','pong')
            await self.write(frame)
            return bytearray()  #对于pingpong 不处理
        elif opcode==0x9:  #如果是pong
            frame=self.makeframe(b'ping','ping')
            await self.write(frame)
            return bytearray()  #对于pingpong 不处理
        elif opcode==0x1: #如果是text
            return data.decode()
        elif opcode==0x02: #如果是bin
            return data 
        else: #是close
            raise Exception('client close connection')

###############################################################################
#处理http请求   
class WSGIFileWrapper(object):
    #用于处理文件的类
    def __init__(self, fp, buffer_size=1024 * 64):
        self.fp, self.buffer_size = fp, buffer_size
        for attr in 'fileno', 'close', 'read', 'readlines', 'tell', 'seek':
            if hasattr(fp, attr): setattr(self, attr, getattr(fp, attr))

    def __iter__(self):
        buff, read = self.buffer_size, self.read
        part = read(buff)
        while part:
            yield part
            part = read(buff)


class Httpapp:
    '''
    借签和修改自Bottle.py实现了一个简单的HTTP响应程序，只支持GET方法
    未来不打算也不计划实现其他方法，其他方法可以通过WebSocket建立长连接来完成。
    简单实现了字符串，python字典，url的query参数和静态文件的传输
    '''
    BUFFER_SIZE=1024
    def __init__(self):
        self.funcs={}       #记录url的path和响应函数的映射
        self.response=None

    def addfunc(self,url='/',callback=lambda x:x):
        #print(url)
        idx=url.find('/<')
        if idx>-1:  #/jif/<path>     /jif/test.js
            url=url[:idx]
        if url in self.funcs:
            raise Exception('url 冲突请重新定义')
        parts=tuple(url.split('/'))
        self.funcs[parts]=callback

    def removefunc(self,url='/'):
        idx=url.find('<')
        if idx>-1:  #/jif/<path：path>     /jif/test.js
            url=url[:idx]
        parts=tuple(url.split('/'))
        if parts in self.funcs:
            del self.funcs[parts]
            
    def getfunc(self,path):
        #函数匹配使用完整性优先，随后最长路径匹配法，不匹配的后部分为参数
        #例如 path='/get/c'     self.funcs里有{'/get' , '/get/a'} 那么匹配/get
        #例如 path='/get/a'   self.funcs里有{'/get/a/k','/get/a','get' } 那么就匹配/get/a
        #注意：路径path='/a'和'/a/' 是不同的，可以作为两个不同的路径，如果/a存在，/a/会退回到/a
        #所有的退回都会到根，也就是不存在的路径都会退回到主页？这是一个问题
        parts=tuple(path.split('/'))
        for i in range(len(parts),1,-1):
            tmp=parts[:i]
            if tmp in self.funcs:
                return self.funcs[tmp],parts[i:]
            tmp=tmp[:i-1]+tuple([''])
            if tmp in self.funcs:
                return self.funcs[tmp],parts[i-1:]
        return None,None
    def route(self,url,method='GET'):
        """
            添加路由和回调函数的装饰器，只支持GET方法
        """
        def wrapper(handler):
            self.addfunc(url, handler)
        return wrapper

    def _cast(self,out,request_env,response):
        
        if not out:
            response['headerdic']['Content-Length'] = '0'
            return []
        
        #实现字典的(字典->json)
        if isinstance(out, dict) and 'body' not in out:
            #Attempt to serialize, raises exception on failure
            out = json.dumps(out)
            #Set content type only if serialization successful
            response['headerdic']['Content-Type'] = 'application/json'
                
        #先实现字符串的的
        # Join lists of byte or unicode strings. Mixed lists are NOT supported
        if isinstance(out, (tuple, list))\
        and isinstance(out[0], (bytes, str)):
            out = out[0][0:0].join(out)  # b'abc'[0:0] -> b''
        # Encode unicode strings
        if isinstance(out, str):
            out = out.encode('utf-8')
        # Byte Strings are just returned
        if isinstance(out, bytes):
            response['headerdic']['Content-Length'] =  f'{len(out)}'
            return [out]
        if isinstance(out, dict) and 'body' in out:  #处理static file
            response['headerdic'].update(out['args'])
            return self._cast(out['body'],request_env,response)
        if hasattr(out, 'read'):                    #处理文件
            if 'wsgi.file_wrapper' in request_env:
                return request_env['wsgi.file_wrapper'](out)
            elif hasattr(out, 'close') or not hasattr(out, '__iter__'):
                return WSGIFileWrapper(out,self.BUFFER_SIZE)
        raise Exception('转换失败')

    def wsgi(self, environ, start_response):
        """ The Httpapp WSGI-interface. """
        response={'status_line':'200 OK','headerdic':{'Content-Length':'0','Content-Type':'text/html; charset=UTF-8'}} #默认初始化
        
        path=environ.get('PATH_INFO','/')
        query=environ.get('QUERY_STRING','')

        callback,args=self.getfunc(path)

        if callback==None: 
            return self.error(environ,start_response,URL_ERROR_HTML)
        #print(path,callback,args)
        #解析url中的query参数
        if query:
            query_dic={}
            for i in query.split('&'):
                key,value=i.split('=',1)
                query_dic[key]=value
            environ['query_dict']=query_dic
        environ['args']=args
        out=callback(environ)          #根据Bottle中out还要_cast处理
        out = self._cast(out,environ,response)       #用来处理callback函数返回输出out(字节串)
                
        headerlist=list(response['headerdic'].items())  #200 ok,[(),()]
        start_response(response['status_line'], headerlist)  #headerlist=[('Content-Length', '24'), ('Content-Type', 'text/html; charset=UTF-8')]
        return out
    
    def __call__(self, environ, start_response):
        """ Each instance of :class:'Httpapp' is a WSGI application. """
        try:
            return self.wsgi(environ, start_response)
        except Exception as e :
            print(e)
            return self.error(environ,start_response,'服务器内部错误!<br>'+str(e)) 

    def error(self, environ, start_response,msg=None):
        #错误的http请求
        response_headers=[('Content-Type','text/html; charset=UTF-8')]
        start_response('404 OK', response_headers) 
        if msg==None:
            return [URL_ERROR_HTML.encode()]
        else:
            return [ msg.encode()]

def static_file(filename='index.html', root='./'):
    #filename and root 需要是有效的路径字符串，root需要用/结尾
    #https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types#textjavascript
    resp_dic={'args':{}}
    f=filename.lower()
    if f.endswith('.html'):
        mimetype='text/html'
    elif f.endswith('.js'):
        mimetype='text/javascript'
    elif f.endswith('.css'):
        mimetype='text/css'
    elif f.endswith('.png'):
        mimetype='image/png'
    elif f.endswith('.jpg'):
        mimetype='image/jpeg'
    elif f.endswith('.ico'):
        mimetype='image/x-icon'
    elif f.endswith('.gif'):
        mimetype='image/gif'
    elif f.endswith('.svg'):
        mimetype='image/svg+xml'
    elif f.endswith('.webp'):
        mimetype='image/webp'
    elif f.endswith('.woff'):
        mimetype='font/woff'
    elif f.endswith('.txt'):
        mimetype='text/plain'
    elif f.endswith('.pdf'):
        mimetype='application/pdf'
    elif f.endswith('.zip'):
        mimetype='application/zip'
    else:
        mimetype='application/octet-stream'
    if mimetype.startswith('text/'):
        resp_dic['args']['Content-Type'] = mimetype+'; charset=utf-8' 
    else:
        resp_dic['args']['Content-Type'] = mimetype
    
    #下面4行是为了兼容micropython,Python中直接的读取文件长度的方法
    fpath=root+filename
    stats = os.stat(fpath)
    resp_dic['args']['Content-Length'] = stats[6]
    resp_dic['body'] =  open(fpath, 'rb')
    return resp_dic
    

def servedir(urlbase='/files',root='./'):
    #将整个目录的文件以静态文件发布到http上,目前支持了层级目录
    #但是对于路径中含有空格的目录和非英文字符的文件和目录（如中文，日文等）不支持，
    #为了在micropython运行，未来也不打算支持空格和非英文字符的文件和目录
    def generate_links(urlbase,path,fnames):
        if (urlbase=='/'): urlbase=''
        if path=='':
            links=["<a href='{url}/{i}'>{i}</a>".format(url=urlbase,i=i) for i in fnames]
        else:
            links=["<a href='{url}/{path}/{i}'>{i}</a>".format(url=urlbase,i=i,path=path) for i in fnames]
        return ['<br>'.join(links)]
    def sfile(environ):
        path=environ['args']
        path='/'.join(path) if path else ''
        fullpath=f'{root}{path}'
        if os.stat(fullpath)[0]<20000: #文件夹为了将micropython和python统一
            fnames=os.listdir(fullpath)
            return generate_links(urlbase,path,fnames)
        else:
            return static_file(path,root=root)
    global httpapp
    httpapp.addfunc(urlbase,sfile)


def htroute(url):     
    #httpapp注册接口，使用@htroute('/url')目前只支持GET
    global httpapp
    return httpapp.route(url)

class HttpHandler:
    #每个http请求都会生成一个该对象
    def  __init__(self,reader,writer,app=None):
        self.app=app
        self.reader=reader
        self.writer=writer
        #https://peps.python.org/pep-3333/#environ-variables
        self.env={  'REQUEST_METHOD': 'GET',
                    'SCRIPT_NAME':'',
                    'PATH_INFO':'',
                    'QUERY_STRING':'',
                    'CONTENT_TYPE':'',
                    'CONTENT_LENGTH':'',
                    'SERVER_NAME':'',
                    'SERVER_PORT':'',
                    'SERVER_PROTOCOL':'HTTP/1.1',
                    'wsgi.version':(1,0),
                    'wsgi.url_scheme':'http',
                    'wsgi.input':reader,
                    'wsgi.errors':sys.stderr,
                    'wsgi.multithread':False,
                    'wsgi.multiprocess':False,
                    'wsgi.run_once':False,
        }
    
    def start_response(self,status='200 OK', response_headers=[('Content-Type','text/plain')], exc_info=None):
        if exc_info:
            pass  #当前不实现，留在以后
        server=self.env['SERVER_NAME']
        response_headers.append(("Server",server))
        #产生http的响应头
        self.headers=self.generateheaders(status,response_headers)
        return self.write
    
    async def run(self,env):
        #每个http请求都会生成一个HTTPHandler对象，不会污染self.env的值
        self.env.update(env)
        #用于处理更长数据的请求,如post,将请求的东西全部注入到self.env中
        #下面的两种方法，第一种在esp32的micropython中使用，第二种在计算机中应当分别使用
        if hasattr(asyncio,'to_thread'):
            results=await asyncio.to_thread(self.app,self.env,self.start_response)
        else:
            results=self.app(self.env,self.start_response)  ##app处理后返回的是out迭代器(即已发送的数据)
        await self.write(results)
    
    async def write(self,datas):
        #向浏览器发送响应
        self.writer.write(self.headers) #先发送http的响应头
        await self.writer.drain()
        for d in datas:
            self.writer.write(d)
            await self.writer.drain()
        if hasattr(datas,'close'):
            datas.close()
        self.writer.close()
        await self.writer.wait_closed()  #关闭连接

    def generateheaders(self,status="200 OK",response_headers=[('Content-Type','text/plain')]):  
        #生成HTTP的响应头
        pro=self.env['SERVER_PROTOCOL']
        headers=f'{pro} {status}\r\n'
        for tu in response_headers:
            headers+=f'{tu[0]}: {tu[1]}\r\n'
        return headers.encode()+b'\r\n'

        
#post, head, update, delete 等http方法的响应
HTTP_UNSUPPORTED_RSP='{} 511 Network Authentication Required\r\n\r\n'

async def client_dispatch(reader, writer):
    #请求分配器，判断请求类型http,websocket和mtassocket，根据类型分配执行器
    remoteip,remoteport = writer.get_extra_info('peername')     
    print(f'链接来自于：{remoteip}:{remoteport}')  #使用日志
    try: 
        #后期要注意超长的连接，一行一直不结束，对于websocket和http就是请求
        data=await reader.readline()  
        data=data.decode().rstrip() #解码为字符串
        print(f'请求头长度:{len(data)}字节,内容:{data}')
    except Exception as e:  #是一个非法的链接，直接关闭返回
        print(f'invalid connection error[0], {e}')
        return 
    try:
        method, path, protocal = data.split()  #example:GET / HTTP/1.1
        #按照wsgi的格式进行请求头的解析
        request_env={'QUERY_STRING':''}
        if '?' in path:  #处理请求中的参数
            path,querystring=path.split('?')
            request_env['QUERY_STRING']=querystring
        request_env['PATH_INFO']=path
        request_env['REQUEST_METHOD']=method.upper()
        request_env['SERVER_PROTOCOL']=protocal
        request_env['client_ip']=remoteip
        request_env['client_port']=remoteport
        request_env['SERVER_NAME']=SERVER
        request_env['SERVER_PORT']=SERVER_PORT
    
        #判断HTTP和WEBSOCKET请求
        if protocal.startswith('HTTP'):
            if method=='GET':       #只支持GET请求
                request_env['wsgi.url_scheme']='https' if 'https' in protocal.lower() else 'http'
                request_headers={}  #保存http请求头中的信息
                #解析http请求头
                while True:
                    data=await reader.readline()
                    data=data.decode().rstrip()
                    if data=='':  #http请求头部结束
                        break
                    k,v= data.split(': ')
                    request_headers[k]=v.strip()
                request_env['request_headers']=request_headers
                #判断链接是http或websocket
                if 'Sec-WebSocket-Key' in request_headers:  #表示是WebSocket连接
                    print('websocket connection')
                    websockethandler=WebsocketHandler(reader,writer,websocketapp)
                    await websockethandler.run(request_env)
                else: #http连接
                    httphandler=HttpHandler(reader,writer,httpapp)
                    await httphandler.run(request_env)
            else:
                writer.write(HTTP_UNSUPPORTED_RSP.format(method).encode())
                await writer.drain()
                raise Exception('Unsupported HTTP method, error[1]')
        elif "MTAS-SOCKET" in protocal:
            print('MTAS-SOCKET connection')
            request_env['wsgi.url_scheme']='mtassocket'
            mtassockethandler=MtassocketHandler(reader,writer,mtassocketapp)
            await mtassockethandler.run(request_env) 
        else:
            raise Exception("Unsupported protocol error[2]")  
    
    except Exception as e:
        print('error happenned when handling request:',e)
        await asyncio.sleep(1) #保证发送数据完成才关闭，兼容性
        writer.close()
        #await writer.wait_closed() 
    
    
######################################################################
#默认的app应用
httpapp=Httpapp() 
websocketapp=Websocketapp()
mtassocketapp=Mtassocketapp()



#设置app的接口
def setapp(htapp=None,wsapp=None,scapp=None):
    global httpapp,websocketapp,mtassocketapp
    if htapp:
        httpapp=htapp
    if wsapp:
        websocketapp=wsapp
    if scapp:
        mtassocketapp=scapp
    
#####################################################################
#在python的version >= 3.7中使用main
async def main(addr='0.0.0.0',port=8888,isssl=False):
    if isssl:
        sslcontext = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        sslcontext.load_cert_chain('./cert.pem', './cert.key')
        #sslcontext.load_default_certs()
        server = await asyncio.start_server(
            client_dispatch, addr, port,ssl=sslcontext)
    else:
        server = await asyncio.start_server(
            client_dispatch, addr, port)
    async with server:
        await server.serve_forever()


#####################################################################
#主事件循环，暴露出来，以供以后添加其他协程到事件循环中
LOOP=asyncio.new_event_loop() if hasattr(asyncio,'new_event_loop') else asyncio.get_event_loop()


def run(addr='0.0.0.0',port=8888,httpapp=None,websocketapp=None,socketapp=None,isssl=False):
    #服务器启动入口
    global SERVER_PORT
    SERVER_PORT=port
    setapp(httpapp,websocketapp,socketapp)
    print('server starting at {}:{}\n'.format(addr,port))
    py_ver=sys.version.split('.') 
    if py_ver[0] !='3' :
        raise Exception('only support python3.6 or higher')
    ver=int(py_ver[1])
    #print(ver)
    if ver>=7:
        coro=main(addr,port,isssl)
        LOOP.create_task(coro)
        LOOP.run_forever()
    else:
        #在python的version < 3.7
        coro = asyncio.start_server(client_dispatch, addr, port)
        LOOP.create_task(coro)
        LOOP.run_forever()
        
#####################################################################
#测试MTAS的app   
#httpapp 符合Python WSGI 规范
def demohttpapp():  
    #提供了一个最简单的WSGI HTTP响应和websocket响应的例子     
    def httpapp(environ, start_response):
        #a test wsgi http app
        #print(environ)
        #print(type(start_response))
        status = "200 OK"
        response_headers = [('Content-Type', 'text/html')]
        start_response(status, response_headers)
        path = environ['PATH_INFO'][1:] or 'This is a Demo Index Page!<br>The MTAS Server is running!'
        return [f'<h1>{path}</h1>'.encode()]    
    return httpapp

async def demopublisher(env,data=None):   #接受env，data，返回数据，类型
    #simulate image publisher
    await asyncio.sleep(1)
    return b'MTAS publisher','text'

async def demosubscriber(env,data=None):   #接受env，data，返回数据，类型
    print(data)


async def demoserver(env,data=None):
    print(data)
    return str(data+'='+str(eval(data))).encode(), 'text'

async def democlient(env,data=None):  
    if data==None: #发起请求
        import random
        x=random.randint(1,100)
        y=random.randint(1,100)
        req=f'{x}+{y}'
        env['reqdata']=req
        print('send request: ',req)
        return req.encode(), 'text'
    #处理响应
    reqdata=env['reqdata']
    print(f'response from server: {reqdata}={data}')

async def demorawpub(env):
    #asdf
    return b'hello world', 'text'


if __name__=='__main__':
    print('starting a demo server')
    addr,port='0.0.0.0',8888

    #websocket demo  
    wsapp=Websocketapp()
    wsapp.addfunc('/publisher', 'publisher', demopublisher)
    #const ws=new WebSocket('ws://localhost:8888/publisher')
    #ws.onmessage=(m)=>{console.log(m.data)}
    wsapp.addfunc('/subscriber','subscriber', demosubscriber)
    #const ws=new WebSocket('ws://localhost:8888/subscriber')
    #ws.send('asdfasdf')
    wsapp.addfunc('/server', 'server', demoserver)
    #const ws=new WebSocket('ws://localhost:8888/server')
    #ws.onmessage=(m)=>{console.log(m.data)}
    #ws.send('3+40')
    wsapp.addfunc('/client', 'client', democlient)
    #wsclient=new WebSocket('ws://localhost:8888/client'); 
    #wsclient.onmessage=(msg)=>{let res=eval(msg.data);console.log(msg.data+'='+res); setTimeout(()=>wsclient.send(res+''),1500) }

    #mtassocket demo
    scapp=Mtassocketapp()
    scapp.addfunc('/publisher','publisher',demopublisher)
    scapp.addfunc('/subscriber','subscriber',demosubscriber)
    scapp.addfunc('/server','server',demoserver)
    scapp.addfunc('/client','client',democlient)
    scapp.addfunc('/rawpub', 'rawpub', demorawpub)

    servedir('/', './')
    run(addr,port,httpapp=None,websocketapp=wsapp,socketapp=scapp)
    #run(addr,port,httpapp=demohttpapp(),websocketapp=wsapp,socketapp=scapp)
