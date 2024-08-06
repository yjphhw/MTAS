#从传感器中获取数据

import socket
import threading

class PubSk(threading.Thread):
    def __init__(self,ip,port):
        super().__init__(daemon=True)
        self.ip=ip
        self.port=port 
        self.start()
    def run(self):
        # 创建 socket 对象
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((self.ip, self.port))
        # 发送消息给服务器
        message_to_send = "publisher /publisher MTAS-SOCKET1.0\r\n"  #握手帧:method url MTAS-SOCKET1.0\r\n+数据帧：#99999999data:payload
        client_socket.send(message_to_send.encode())
        while True:
            msglength=int(client_socket.recv(8))
            msgtype=client_socket.recv(1)[0]
            if msgtype==49 : #49=='1' #'text'
                data=client_socket.recv(msglength).decode()
                print(f'msg from publisher:{data}')


class SubSk(threading.Thread):
    def __init__(self,ip,port):
        super().__init__(daemon=True)
        self.ip=ip
        self.port=port 
        self.start()

    def run(self):
        # 创建 socket 对象
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((self.ip, self.port))
        # 发送消息给服务器
        message_to_send = "subscriber /subscriber MTAS-SOCKET1.0\r\n"  #握手帧:method url MTAS-SOCKET1.0\r\n+数据帧：#99999999data:payload
        client_socket.send(message_to_send.encode())
        num=0
        while True:
            msg=f'this the {num}th message!'
            frame=makeframe(msg.encode(),'text')
            print(f'sendmsg: {msg}')
            client_socket.send(frame)
            num+=1
            time.sleep(1)
def makeframe(data:bytes=b'{}',tp='text'):    
    #生成数据帧，数据帧由3部分构成：负载长度（payload length）+数据类型+数据
    #负载长度为8个字节，表示数据部分的长度，使用填充0的ascii码表示，如数据长度为1024时，表示为b'00001024'
    #数据类型是1个字节，ascii码为b'1'时表示bin(二进制类型)，ascii码为b'0'时表示文本类型
    #data是bytes类型，对于文本需要在传入前调用encode()方法编码
    #type是'text'或'bin'
    frame=b''
    datalength=len(data)       #表示有多少个字节    8字节数据长度+data
    # 使用to_bytes方法将整数转换为指定长度的字节串
    typecode=1 if tp=='text' else 0
    lendatastr=f'{datalength:08}{typecode}'
    frame += lendatastr.encode()
    return frame+data

import random
class ServerSk(threading.Thread): #测试服务器，此处应当为客户商
    def __init__(self,ip,port):
        super().__init__(daemon=True)
        self.ip=ip
        self.port=port 
        self.start()

    def run(self):
        # 创建 socket 对象
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((self.ip, self.port))
        # 发送消息给服务器
        message_to_send = "server /server MTAS-SOCKET1.0\r\n"  #握手帧:method url MTAS-SOCKET1.0\r\n+数据帧：#99999999data:payload
        client_socket.send(message_to_send.encode())
        while True:
            msg=f'{random.randint(0,100)}+{random.randint(0,100)}'
            frame=makeframe(msg.encode(),'text')
            print(f'msg to server: {msg}')
            client_socket.send(frame)
            time.sleep(1)
            msglength=int(client_socket.recv(8))
            msgtype=client_socket.recv(1)[0]
            if msgtype==49 : #49=='1' #'text'
                data=client_socket.recv(msglength).decode()
                print(f'msg from server {data}')


class ClientSk(threading.Thread): #测试客户端，此处应当为服务器
    def __init__(self,ip,port):
        super().__init__(daemon=True)
        self.ip=ip
        self.port=port 
        self.start()

    def run(self):
        # 创建 socket 对象
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((self.ip, self.port))
        # 发送消息给服务器
        message_to_send = "client /client MTAS-SOCKET1.0\r\n"  #握手帧:method url MTAS-SOCKET1.0\r\n+数据帧：#99999999data:payload
        client_socket.send(message_to_send.encode())
        while True:
            msglength=int(client_socket.recv(8))
            msgtype=client_socket.recv(1)[0]
            if msgtype==49 : #49=='1' #'text'
                data=client_socket.recv(msglength).decode()
                print(f'msg from client {data}')

            msg=f'{data}={eval(data)}'
            frame=makeframe(msg.encode(),'text')
            print(f'msg to client: {msg}')
            client_socket.send(frame)
            time.sleep(1)
            


if __name__=='__main__':
    import time
    ip='127.0.0.1'
    port=8888
    th=[PubSk(ip,port) for i in range(1)]
    SubSk(ip,port)
    ServerSk(ip,port)
    ClientSk(ip,port)
    while True:
        time.sleep(1)