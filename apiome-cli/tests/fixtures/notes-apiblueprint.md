FORMAT: 1A

# Notes API

A minimal API Blueprint saved as Markdown (MFI-16.4 fixture).

## Notes [/notes]

### List notes [GET]

+ Response 200 (application/json)
    + Attributes (array[Note])

# Data Structures

## Note (object)
+ id: 1 (number, required) - Note id.
+ text: Buy milk (string, required) - Note text.
