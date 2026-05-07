var tStart,tEnd;
function init() {
    setDimensions();
    maintainAspectRatio();
    slideHandlers();
    showVid();
    console.log("Game Controller Initialized");
}

/* SFE RULE 11: Call init directly at the end of script instead of using onload/ready events */
init();

function slideHandlers(){
    $("#slideCover img,#slideCover video").on("touchstart",function(e){
        tStart=e.originalEvent.touches[0].pageX
    })
    $("#slideCover img,#slideCover video").on("touchend",function(e){
        tEnd=e.originalEvent.changedTouches[0].pageX
        swipeDirection();
    })
    
    // Polyfill for SFE+ preview: natively handle data-next-file clicks in browser
    $(document).on("click touchend", "[data-next-file]", function(e) {
        e.preventDefault();
        e.stopPropagation();
        var target = $(this).attr("data-next-file");
        if (target && target !== "javascript:void(0)") {
            window.location.href = target;
        }
    });
}

function maintainAspectRatio(){
    $(window).on("resize",function(){
        setDimensions();
    })
}

function setDimensions(){
    // var limit=$("body").height();
    // limit=limit * .95
    var bodyWidth=$("body").width();
    var bodyHeight=$("body").height();

    var setWidth;
    if(bodyWidth > bodyHeight && bodyHeight > (bodyWidth * .70) ){
        setWidth = bodyWidth;
    }
    else if(bodyHeight > bodyWidth){
        setWidth=bodyHeight;
    }
    else{
        setWidth=(bodyHeight * .43) + bodyHeight
    }
    console.log(setWidth)
    var aspectRatioObj=$("#aspect-ratio-container");
    aspectRatioObj.width(setWidth)
    var width=aspectRatioObj.width();
    //set aspect-ratio-container height to 70% size of its width
    aspectRatioObj.height(width * .75); 
    $("html,body").css("min-height",width * .75)
}

function swipeDirection(){
    // console.log(tStart,tEnd)
    if(Math.abs(tStart - tEnd) > 100){
        if(tStart < tEnd){
            toRight()
        }
        else{
            toLeft()
        }
    }
}

function getNext(){
    return $("#slideCover img").attr("data-next-file");
}
function getPrev(){
    return $("#slideCover img").attr("data-previous-file");
}

function toLeft(){
    // console.log("go to next",getNext());
    if(getNext() != ""){
        window.open(getNext(),"_self");
    }
    

}
function toRight(){
    // console.log("go to previous",getPrev());
    if(getPrev() != ""){
        window.open(getPrev(),"_self");
    }
}

function showVid(){
    if($("#slideVid").length > 0){
        playVid();
    }
}

function playVid(){
    var play=document.getElementById("slideVid");
    if(play) {
        play.loop=true;
        play.play();
    }
}

/* SFE COMPLIANCE: Menu toggle function */
function toggleMenu(menuId) {
    var menu = document.getElementById(menuId);
    if (!menu) return;
    if (menu.style.display === "flex") {
        menu.style.display = "none";
    } else {
        menu.style.display = "flex";
    }
}