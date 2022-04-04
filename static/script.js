var cursor;
var canvas;
var selected;
var selectedColor;

var image = new Image();
image.onload = function() {
    canvas.getContext('2d').drawImage(image, 0, 0);
}

function refresh() {
    fetch('/image/' + cursor)
        .then(response => {
            cursor = response.headers.get('X-Cursor');
            return response.blob();
        })
        .then(blob => {
            image.src =  URL.createObjectURL(blob)
        })
}

$(document).ready(function() {
    canvas = document.createElement("canvas");
    document.body.appendChild(canvas);
    canvas.width  = 1000;
    canvas.height = 1000;
    var context = canvas.getContext("2d");
    fetch('/image/full')
        .then(response => {
            cursor = response.headers.get('X-Cursor');
            return response.blob();
        })
        .then(blob => {
            image.src =  URL.createObjectURL(blob)
        })
    setInterval(refresh, 500);
    var cl = canvas.offsetLeft + canvas.clientLeft;
    var ct = canvas.offsetTop + canvas.clientTop;

    var colorFlex = document.createElement("div");
    colorFlex.style.display = "flex";
    colorFlex.style.width = "1000px";
    colorFlex.style.height = "30px";
    fetch('/colors').then(
        data => data.json()
    ).then(
        colors => colors.map((color, index) => {
            var colorBox = document.createElement("div");
            colorBox.style.flexGrow = "1";
            colorBox.style.backgroundColor = color[1];
            colorBox.title = color[0];
            colorBox.onclick = function() {
                console.log(selected);
                if (typeof selected !== 'undefined') {
                    selected.classList.remove('selected');
                }
                selected = this;
                selected.classList.add('selected');
                selectedColor = index;
            }
            colorFlex.appendChild(colorBox);
        })
    );
    document.body.appendChild(colorFlex);

    canvas.addEventListener('click', function(event) {
        var x = event.pageX - cl,
            y = event.pageY - ct;
        fetch('/image/place/' + x + '/' + y + '/' + selectedColor);
    });

//    var clear = document.createElement("button");
//    clear.innerHTML = "Clear";
//    clear.addEventListener('click', function(event) {
//        fetch('/image/clear');
//    });
//    document.body.appendChild(clear);
});
