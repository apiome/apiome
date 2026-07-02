/*
 * ONC RPC / XDR example — a key/value store program (RFC 4506 / RFC 5531).
 *
 * This is an `.x` file: the RPC language (RPCL) processed by rpcgen. XDR type
 * declarations (`struct`, `enum`, `typedef`, `union ... switch`) define the data
 * shapes that become catalog classes; the `program`/`version`/`procedure` block at
 * the bottom declares the RPC surface (each procedure has a number, argument type,
 * and return type). `string<>` and `opaque<>` are variable-length; `<N>` bounds.
 */

enum kv_status {
    KV_OK = 0,
    KV_NOT_FOUND = 1,
    KV_ERROR = 2
};

typedef string kv_key<256>;

struct kv_entry {
    kv_key key;
    opaque value<1024>;
};

union kv_get_res switch (kv_status status) {
case KV_OK:
    kv_entry entry;
default:
    void;
};

struct kv_put_args {
    kv_key key;
    opaque value<1024>;
};

program KV_PROG {
    version KV_VERS {
        kv_get_res KV_GET(kv_key) = 1;
        kv_status  KV_PUT(kv_put_args) = 2;
        kv_status  KV_DELETE(kv_key) = 3;
    } = 1;
} = 0x20000001;
