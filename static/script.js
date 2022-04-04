var cursor;
var canvas;
var colorSelect;

var image = new Image();
image.onload = function() {
    // draw image...
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

    colorSelect = document.createElement("select");
    fetch('/colors').then(
        data => data.json()
    ).then(
        colors => colors.map((color, index) => {
            var option = document.createElement("option");
            option.innerHTML = color;
            option.value = index;
            colorSelect.appendChild(option);
        })
    );
    document.body.appendChild(colorSelect);

    // Add event listener for `click` events.
    canvas.addEventListener('click', function(event) {
        var x = event.pageX - cl,
            y = event.pageY - ct;
        fetch('/image/place/' + x + '/' + y + '/' + colorSelect.value)
    });

    var clear = document.createElement("button");
    clear.innerHTML = "Clear";
    clear.addEventListener('click', function(event) {
        fetch('/image/clear');
    });
    document.body.appendChild(clear);
});
