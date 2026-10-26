#!/bin/bash

# Read the JSON file into a variable
args=$(cat samples_to_create.json)

# Call the dbt macro with the JSON content as an argument
dbt run-operation create_sample_source --args "$args"
