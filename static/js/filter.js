let currentServiceFilters = new Set()
let currentPriorityFilters = new Set()
function filterTable(selectedFilters, cell){
    console.log("Service Filters", currentServiceFilters)
    console.log("Priority Filters", currentPriorityFilters)
    
    const rows = document.querySelectorAll(".incident-list-item")

    rows.forEach(row => {

        filter = row.cells[cell].textContent.toLowerCase()
        console.log("Filter: ", filter)
        console.log(currentServiceFilters.has(filter))
        if(currentServiceFilters.size === 0 || currentServiceFilters.has(filter)){
            row.style.display = ""
        } else {
            row.style.display = "none"
        }
        if(currentPriorityFilters.size === 0 || currentPriorityFilters.has(filter)){
            row.style.display = ""
        }  else {
            row.style.display = "none"
        }
    })
}
function priorityFilterTable(){
    const selectedPriorities = Array.from(document.querySelectorAll('.filter-priority:checked')).map(cb => cb.value)
    for(let filter of currentPriorityFilters){
        if(!selectedPriorities.includes(filter)){
            currentPriorityFilters.delete(filter)
        }
    }
    selectedPriorities.forEach(e => currentPriorityFilters.add(e))
    filterTable(selectedPriorities, 4)
}
function serviceFilterTable(){
    const selectedServices = Array.from(document.querySelectorAll('.filter-service:checked')).map(cb => cb.value.toLowerCase())
    console.log(selectedServices)
    for(let filter of currentServiceFilters){
        if(!selectedServices.includes(filter)){
            currentServiceFilters.delete(filter)
        }
    }
    selectedServices.forEach(e => currentServiceFilters.add(e))
    filterTable(selectedServices, 3)
}
function clearFilters(){
    document.querySelectorAll(".filter-priority").forEach(cb => cb.checked = false)
    filterTable()
}