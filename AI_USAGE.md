# AI usage

## Tools

- **ChatGPT:** Used for help understanding some project requirements, debugging API errors, and understanding cursor-based pagination.
- **VS Code:** Used to write and edit the code and project documentation.
- **PowerShell:** Used to run tests and inspect project files.

## What AI got wrong

An initial cursor implementation used Base64 encoding of parcel IDs, which did not guarantee that the cursor had actually been issued by the API. I learned that checking whether the decoded parcel ID existed was not enough, so I changed the implementation to track issued cursors and added a test for an unknown cursor.

## In my own words

### 1. Why does `listParcels` need a cursor rather than an offset?

A cursor helps us continue from where the last page ended, even if some parcels change state while we are browsing. This helps prevent skipping or repeating parcels when the list changes.

### 2. Which of your four operations would break the courier app if you renamed one field, and who would have to approve that change?

Renaming a field in `createParcel` or `getParcel` could break the courier app if it expects the old field name. The courier app team and the merchant integration team should approve the change to make sure their systems continue to work with the API.
