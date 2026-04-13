;; Capture Python function definitions and an optional nested docstring.
(function_definition
  name: (identifier) @function.name
  parameters: (parameters) @function.parameters
  body: (block
    .
    (expression_statement
      (string) @function.docstring)?)) @function.definition

(decorated_definition
  (decorator)+ @function.decorator
  definition: (function_definition
    name: (identifier) @function.name)) @function.decorated_definition

