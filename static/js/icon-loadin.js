
document.addEventListener("DOMContentLoaded", () => {

    const SELECTORS = {
        navbar: ".navbar",
        navBtns: ".nav-btn:not(.logout-btn)",//all the nav btns except the logout
        bell: ".nav-notification-btn",
        card:".card",
        cardParts:".card > .form-header, .card>.lead, .card>.actions",
        goldBtns:".btn-gold",

    };

    const NAVY =  getComputedStyle(document.documentElement) .getPropertyValue("--navy-dark").trim() || "#052b6e";

    const GOLD = getComputedStyle(document.documentElement) .getPropertyValue("--gold").trim() || "#d4af37";


    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    function onHover(element,keyframes,duration = 200){
        let anim = null;

        element.addEventListener("mouseenter", ()=>{
            if (!anim){
                anim = element.animate(keyframes, { duration, easing: "ease-out", fill: "forwards" 

                });
            }else{
                anim.playbackRate = 1;
                anim.play();
            }
    
        });
    


    element.addEventListener("mouseleave",()=>{
         
        if (anim && anim.currentTime >0){
            anim.playbackRate = -1;
            anim.play()
        }
        

    });
    }
const navbar = document.querySelector(SELECTORS.navbar);
if (navbar){
    navbar.animate(
        [ { opacity: 0, transform: "translateY(-100%)" },
                { opacity: 1, transform: "translateY(0)" },
            ],
             { duration: 400, easing: "ease-out" }
    );
}

const card = document.querySelector(SELECTORS.card);
if (card){
    card.animate(
        [
            { opacity: 0, transform: "translateY(20px)" },
            { opacity: 1, transform: "translateY(0)" },
        ],
        { duration: 500, easing: "ease-out" }
    );
}

document.querySelectorAll(SELECTORS.cardParts).forEach((part,index)=>{
    part.animate(
        [
                { opacity: 0, transform: "translateY(20px)" },
                { opacity: 1, transform: "translateY(0)" },
        ],
        {
                duration: 500,
                delay: 150 + index * 150,   // each one starts 0.15s after the last
                easing: "ease-out",
                fill: "backwards",
        }
    );
});

document.querySelectorAll(SELECTORS.navBtns).forEach((btn)=>{

    onHover(btn,[
            { backgroundColor: "transparent", color: GOLD },
            { backgroundColor: GOLD, color: NAVY },
    ]);
     const icon = btn.querySelector("svg");
        if (icon) {
            onHover(icon, [
                { transform: "translateY(0) scale(1)" },
                { transform: "translateY(-2px) scale(1.1)" },
            ]);
        }

    btn.addEventListener("mousedown", () => {
            btn.animate(
                [
                    { transform: "scale(1)" },
                    { transform: "scale(0.96)" },
                    { transform: "scale(1)" },
                ],
                { duration: 200, easing: "ease-out" }
            );
        });
    });

    const bell = document.querySelector(SELECTORS.bell);
    const bellIcon = bell ? bell.querySelector("svg") : null;
    if (bellIcon) {
        bell.addEventListener("mouseenter", () => {
            bellIcon.animate(
                [
                    { transform: "rotate(0)" },
                    { transform: "rotate(-12deg)" },
                    { transform: "rotate(12deg)" },
                    { transform: "rotate(0)" },
                ],
                { duration: 400, easing: "ease-in-out" }
            );
        });
    }


document.querySelectorAll(SELECTORS.goldBtns).forEach((btn) => {
        onHover(btn, [
            { transform: "translateY(0)",    boxShadow: "0 0 0 rgba(0,0,0,0)" },
            { transform: "translateY(-3px)", boxShadow: "0 6px 16px rgba(0,0,0,0.25)" },
        ], 150);
    });
});