let cursor;
let canvas;
let selected;
let selectedColor;

function drawImage(data) {
    let image = new Image();
    image.onload = function() {
        canvas.getContext('2d').drawImage(image, 0, 0);
    }
    image.src = URL.createObjectURL(data);
}

function refresh() {
    let path;
    if (!cursor) {
        path = '/image/full';
    } else {
        path = '/image/' + cursor;
    }
    fetch(path)
    .then(response => {
        cursor = response.headers.get('X-Cursor');
        return response.blob();
    })
    .then(blob => {
        drawImage(blob);
    })
}

window.onload = function() {
    canvas = document.createElement("canvas");
    document.body.appendChild(canvas);
    canvas.width  = 1000;
    canvas.height = 1000;
    fetch('/image/full')
        .then(response => {
            cursor = response.headers.get('X-Cursor');
            return response.blob();
        })
        .then(blob => {
            drawImage(blob);
        })
    setInterval(refresh, 500);
    let cl = canvas.offsetLeft + canvas.clientLeft;
    let ct = canvas.offsetTop + canvas.clientTop;
    let colorFlex = document.createElement("div");
    colorFlex.style.display = "flex";
    colorFlex.style.width = "1000px";
    colorFlex.style.height = "30px";
    fetch('/colors').then(
        data => data.json()
    ).then(
        colors => colors.map((color, index) => {
            let colorBox = document.createElement("div");
            colorBox.style.flexGrow = "1";
            colorBox.style.backgroundColor = color[1];
            colorBox.title = color[0];
            if (!selected) {
                selected = colorBox;
                selected.classList.add('selected');
                selectedColor = index;
            }
            colorBox.onclick = function() {
                selected.classList.remove('selected');
                selected = this;
                selected.classList.add('selected');
                selectedColor = index;
            }
            colorFlex.appendChild(colorBox);
        })
    );
    document.body.appendChild(colorFlex);

    canvas.addEventListener('click', function(event) {
        let x = event.pageX - cl,
            y = event.pageY - ct;
        fetch('/image/place/' + x + '/' + y + '/' + selectedColor);
        let ctx = canvas.getContext('2d');
        ctx.beginPath();
        ctx.fillStyle = selected.style.backgroundColor;
        ctx.rect(Math.floor(x / 20) * 20, Math.floor(y / 20) * 20, 20, 20);
        ctx.fill();
    });

//    var clear = document.createElement("button");
//    clear.innerHTML = "Clear";
//    clear.addEventListener('click', function(event) {
//        fetch('/image/clear');
//    });
//    document.body.appendChild(clear);
};
