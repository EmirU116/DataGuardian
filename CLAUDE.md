# Project
Data Quality Guardian is helping with spotting bad data in a dataset. Which can be helpful for cleaning for datasets. This can include spotting duplicates, missing values, fixing data types of the columns, standardize formats, validating data, cleaning text.

for more details of the projct, use @./README.md file as a reference to understand what the project is about. 

## Tech Stack
- Frontend: Streamlit (to generate different graphs and frontend for the data)
- Language: Python
- Packet handling command: ```pip install <packet-name>```
- File to use: use ```.ipynb``` to transform dataset step-by-step with a explaination.

## Folder structure
- ```./src``` folder is for the source code.
- ```./data``` folder is a place for datasets files like .csv.
- ```./data/raw-data``` folder is where the original dataset should be placed. basically where there is no changes of.
- ```./docs``` where all the docummentation lives.
- ```requirement.txt``` file is a place for the package libraries.

### Codebase rule
- Before writing a feature, you MUST make a plan first before writing any code on the feature. 
    - meaning, thinking about worst-case scenarios, making it work with the system to follow the codebase rules.
- Write comments on code, for easier reading on the codebase and a multi-string to explain how the code works.
- Error-handling is a must, specially when working on APIs
- Writing tests for functions that contains bussiness logic, complex algorithms, or error-prone condidtions. 

### Docummentations
- ```./docs/workflow.md``` add workflows and an explanation about the workflow, for example what it solves, the problems, and why using this workflow. This can be like for example, git branch workflow, for each feature, create a branch and work on the feature branch and never on the main branch. After feature is done, create a PR to main, dev or testing branch, then delete the branch when and if the PR is accepted.
- ```./docs/coding-style.md``` explaining what the projects coding style, how to structure code.

### Repeatition work
- Repeated tasks or multiple step tasks should be turned into a skill.
