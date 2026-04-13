;; Capture Java methods, annotations, and nearby Javadoc-bearing declarations.
(method_declaration
  (modifiers
    (annotation) @method.annotation)*
  name: (identifier) @method.name) @method.declaration

(constructor_declaration
  (modifiers
    (annotation) @method.annotation)*
  name: (identifier) @method.name) @method.declaration

(block_comment) @method.javadoc

