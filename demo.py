#from bottle import route,app,static_file
from mtas import run,wsroute,Jsonrpc,skroute,htroute,static_file
import asyncio 
import numpy as np
import cv2
import json

#服务器作为客户端，接收客户端发来的消息
#测试网页Index中的canvasdraw.js数据
@wsroute('/canvascmd',method='subscriber')
async def subscribertxt(env,data=None): 
    rpc=Jsonrpc.parserequest(data)
    print(rpc.request)



@skroute('/publisher',method='publisher')
async def demopublisher(env,data=None):   #接受env，data，返回数据，类型
    #simulate image publisher
    await asyncio.sleep(1)
    res=np.random.randint(30,127,40,dtype='uint8')
    return res.tobytes(),'text'

@skroute('/subscriber',method='subscriber')
async def demosubscriber(env,data=None):   #接受env，data，返回数据，类型
    print(data)

@skroute('/server',method='server')
async def demoserver(env,data=None):
    print(data)
    return str(data+'='+str(eval(data))).encode(), 'text'

@skroute('/client',method='client')
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



@skroute('/publisher',method='publisher')
async def demopublisher(env,data=None):   #接受env，data，返回数据，类型
    #simulate image publisher
    await asyncio.sleep(1)
    res=np.random.randint(30,127,40,dtype='uint8')
    return res.tobytes(),'text'

@wsroute('/subscriber',method='subscriber')
async def demosubscriber(env,data=None):   #接受env，data，返回数据，类型
    print(data)

@wsroute('/server',method='server')
async def demoserver(env,data=None):
    print(data)
    return str(data+'='+str(eval(data))).encode(), 'text'

@wsroute('/client',method='client')
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

#服务器作为发布者的例子，向连接的客户端发送文本数据
@wsroute('/pubhello',method='publisher')
async def sendhelloworld(env,data=None):
    await asyncio.sleep(1)
    res=np.random.randint(30,127,40,dtype='uint8')
    return res.tobytes(),'text'


#发布者例子，发布二进制数据，图像
@wsroute('/images',method='publisher')
async def sendimage(env,data=None):
    #传输图像的例子
    data=np.random.random((256,256,3))*255
    _,res=cv2.imencode('.png',data.astype('uint8'))
    await asyncio.sleep(1)
    return res.tobytes(),'bin'

#后续需要添加，从客户端接收二进制数据的例子

#服务端例子,接收用户请求,jsonrpc
@wsroute('/rpcserver',method='server')
async def rpcserver(env,data=None):
    rpc=Jsonrpc.parserequest(data)
    #idx=rpc.id
    print(rpc.request)
    if rpc.method=='add':  #通过name可以进行不同命令的执行
        a,b=rpc.params
        res=rpc.success(a+b)
        return res,'text'
    elif rpc.method=='sub':
        a,b=rpc.params
        res=rpc.success(a-b)
        return res,'text'
    else:
        res=rpc.error()
        return res,'text'

#客户端的例子,发送请求，jsonrpc
@wsroute('/rpcclient',method='client')
async def rpcclient(env,data=None):
    #根据data为None则是发送请求，否则就是获得的响应
    if data: 
        if k:=Jsonrpc.parseresponse(data):
            print(k)
    else:
        params=(50*np.random.random(2)).astype('int').tolist()
        res=Jsonrpc.makerequest('add',params=params,id=32)
        return res,'text'


#INDEXHTML=open('./static/index.html','r',encoding='utf-8').read()
'''
@route('/')
def index(): 
    #return 'hello world'
    #return INDEXHTML
    return static_file('index.html',root='./static')

#用于测试上述websocket例子
@route('/ws')
def index(): 
    return static_file('testwebsocket.html',root='./static')

#使用
@route('/json')
def j():
    return dict(a=3,b=4)

#静态文件
@route('/static/<path:path>')
def sfile(path):
    return static_file(path,root='./static')
'''

@htroute('/')
def index(environ): 
    return static_file('index.html',root='./static')

#用于测试上述websocket例子
@htroute('/ws')
def index(environ): 
    return static_file('testwebsocket.html',root='./static')

#字符串,列表
@htroute('/sayhello')
def hello(environ):
    return ("Today is a beautiful day")

#python字典
@htroute('/json')
def getcars(environ):
    cars = [ {'name': 'Audi', 'price': 52642},
        {'name': 'Mercedes', 'price': 57127},
        {'name': 'Skoda', 'price': 9000},
        {'name': 'Volvo', 'price': 29000},
        {'name': 'Bentley', 'price': 350000},
        {'name': 'Citroen', 'price': 21000},
        {'name': 'Hummer', 'price': 41400},
        {'name': 'Volkswagen', 'price': 21600} ]

    return dict(data=cars)

@htroute('/env')
def getenv(environ):
    return {'env':list(environ.keys())}

#静态文件
@htroute('/static/<path:path>')
def sfile(environ):
    path=environ['args']
    path='/'.join(path) if isinstance(path,(tuple,list)) else path
    return static_file(path,root='./static/')

#querystring
@htroute('/compute')
def compute(environ):     #'/compute?a=1&b=4   #传入的都是字符串
    data=environ['query_dict']
    a=data['a']
    b=data['b']
    return f'{int(a)+int(b)}'

@htroute('/add/<a:int>/<b:int>')
def add(environ):
    arg=environ['args']
    a=int(arg[0])
    b=int(arg[1])
    return f'{a+b}'

@htroute('/multi/<a>/<b>/<c>/...')
def multi(environ):
    #http://127.0.0.1:8889/multi/3/4/5/6/6/1/2/3/  返回12960
    arg=environ['args']
    res=1
    for i in arg:
        res*=float(i)
    return f'{res}'
if __name__=='__main__':
    run(addr='127.0.0.1',port=8888,isssl=False)