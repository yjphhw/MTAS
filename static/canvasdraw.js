href = window.location.origin.replace(window.location.protocol, 'ws:') + '/canvascmd'
console.log(href)
var socket = new WebSocket(href)
//不使用接收
socket.onmessage = e => {
    console.log(e.data)
    mes = JSON.parse(e.data)

}
// 获取canvas元素
var canvas = document.querySelector("#myCanvas");
var context = canvas.getContext("2d");

// 设置初始位置
var mouseX = 0;
var mouseY = 0;
var isDrawing = false;

// 监听鼠标按下事件
canvas.addEventListener("mousedown", function (event) {
    isDrawing = true;
    mouseX = event.pageX - canvas.offsetLeft;
    mouseY = event.pageY - canvas.offsetTop;
});

var rpcrequest={"method":"add", "id": "pose", "jsonrpc": "2.0", "params": [3, 4]}
// 监听鼠标移动事件，使用jsonrpc
canvas.addEventListener("mousemove", function (event) {
    if (isDrawing) {
        //console.log("nn")
        console.log(mouseX, mouseY)
        rpcrequest.method='mouseposition'
        rpcrequest.params={x:mouseX, y:mouseY}
        rpcrequest.id=Date.now()
        let cmdstr = JSON.stringify(rpcrequest)
        socket.send(cmdstr)
        var currentX = event.pageX - canvas.offsetLeft;
        var currentY = event.pageY - canvas.offsetTop;

        // 绘制线段
        context.beginPath();
        context.moveTo(mouseX, mouseY);
        context.lineTo(currentX, currentY);
        context.stroke();

        mouseX = currentX;
        mouseY = currentY;
    }
});

// 监听鼠标松开事件
canvas.addEventListener("mouseup", function () {
    isDrawing = false;
});