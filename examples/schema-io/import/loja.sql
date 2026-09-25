-- DDL de referência para `dataipsum schema import` (DD-02 §F.7, §F.9).
--
-- Cobre, num único arquivo:
--   - PK inteira (SERIAL) em `usuarios` e `categorias` -> primary_key.strategy: sequence;
--   - inferência por nome de `cpf` (CHAR(11) -> format: unmasked) e `email` (VARCHAR ->
--     endereço, com `name_column` apontando para `nome`, inferida como `nome_proprio`);
--   - FK simples 1:N em `pedidos.usuario_id` -> rows_from.relation: one_to_many;
--   - tabela-ponte `usuario_categoria` (PK composta = 2 FKs) -> rows_from.relation:
--     many_to_many.
CREATE TABLE usuarios (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(120) NOT NULL,
    cpf CHAR(11) NOT NULL,
    email VARCHAR(120)
);

CREATE TABLE categorias (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(80) NOT NULL
);

CREATE TABLE pedidos (
    id SERIAL PRIMARY KEY,
    usuario_id INT NOT NULL,
    FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
);

CREATE TABLE usuario_categoria (
    usuario_id INT NOT NULL,
    categoria_id INT NOT NULL,
    PRIMARY KEY (usuario_id, categoria_id),
    FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
    FOREIGN KEY (categoria_id) REFERENCES categorias (id)
);
