let currentServiceFilters = new Set()
let currentPriorityFilters = new Set()
function filterTable(selectedFilters, cell){
    
    const rows = document.querySelectorAll(".incident-list-item")
    const selectedServices = Array.from(document.querySelectorAll('.filter-service:checked')).map(cb => cb.value.toLowerCase())
    
    for(let filter of currentServiceFilters){
        if(!selectedServices.includes(filter)){
            currentServiceFilters.delete(filter)
        }
    }
    selectedServices.forEach(e => currentServiceFilters.add(e))
    console.log(currentServiceFilters)
    const selectedPriorities = Array.from(document.querySelectorAll('.filter-priority:checked')).map(cb => cb.value)
    for(let filter of currentPriorityFilters){
        if(!selectedPriorities.includes(filter)){
            currentPriorityFilters.delete(filter)
        }
    }
    selectedPriorities.forEach(e => currentPriorityFilters.add(e))
    console.log(currentPriorityFilters)
    rows.forEach(row => {
        
        priorityFilter = row.cells[4].textContent.toLowerCase()
        serviceFilter = row.cells[3].textContent.toLowerCase()

        if(currentServiceFilters.size === 0 && currentPriorityFilters.size === 0){
            console.log("rows should return")
            row.style.display = ""
        } else {
            if(currentServiceFilters.has(serviceFilter)){
                if(currentPriorityFilters.size === 0){
                    console.log("No priority filters. Matching service filter")
                    row.style.display = ""
                } else if(currentPriorityFilters.has(priorityFilter)){
                    row.style.display = ""
                } else {
                    row.style.display = "none"
                }
            } else if(currentPriorityFilters.has(priorityFilter)) {
                if(currentServiceFilters.size === 0){
                    row.style.display = ""
                } else {
                    row.style.display = "none"
                }
            } else {
                row.style.display = "none"
            }
        }
    })
}
function priorityFilterTable(){
    
    filterTable(selectedPriorities, 4)
}
function serviceFilterTable(){
    

}
function clearFilters(){
    document.querySelectorAll(".filter-priority").forEach(cb => cb.checked = false)
    filterTable()
}