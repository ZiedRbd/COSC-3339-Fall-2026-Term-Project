function filterTable(){
    const selectedPriorities = Array.from(document.querySelectorAll('.filter-priority:checked')).map(cb => cb.value)
    console.log(selectedPriorities)
    const rows = document.querySelectorAll(".incident-list-item")
    console.log(rows)
    rows.forEach(row => {
        console.log(row.cells[4].textContent.toLowerCase())
        priority = row.cells[4].textContent.toLowerCase()
        if(selectedPriorities.length === 0 || selectedPriorities.includes(priority)){
            row.style.display = ""
        } else {
            row.style.display = "none"
        }
    })

}

function clearFilters(){
    document.querySelectorAll(".filter-priority").forEach(cb => cb.checked = false)
    filterTable()
}