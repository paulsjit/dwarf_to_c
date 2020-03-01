#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <assert.h>
#include "list.h"

struct sdecode {
	uint8_t level;
	uint32_t offset;
	uint32_t size;
	uint8_t array;
	uint32_t array_dims[4];
	uint8_t name[128];
	uint8_t type[128];
} __attribute__((packed));

struct member {
	unsigned int id;
	unsigned int level;
	unsigned int offset;
	unsigned int size;
	bool is_array;
	unsigned int dims[4];
	char *name;
	char *type;
	struct list_head link;
	struct list_head children;
	struct member *parent;
};

static uint32_t le32_to_cpu(uint32_t a)
{
	return a;
}

void print(struct member *r, int level)
{
	struct member *m;

	list_for_each_entry(m, &r->children, link) {
		int i;
		for(i = 0; i < level; i++)
			printf(" ");
		printf("%s @%u %s%s%s\n", m->name, m->offset, m->type ? "(" : "", m->type ? m->type : "", m->type ? ")" : "");
		if(!list_empty(&m->children)) {
			print(m, level + 8);
		}
	}
}

int main(int argc, char *argv[])
{
	int f, i;

	if(argc < 2)
		return 0;

	f = open(argv[1], O_RDONLY);
	if(f < 0) {
		printf("Could not open %s\n", argv[1]);
		return 0;
	}

	struct member root;
	root.name = "root";
	INIT_LIST_HEAD(&root.children);

	int cnt = 0;
	int expect_level = 0;
	struct member *parent = &root;
	struct member *last = NULL;
	while(true) {
		struct member *new;
		struct sdecode s;
		int l = read(f, &s, sizeof(s));
		if(l <= 0)
			break;

		new = calloc(1, sizeof(*new));

		new->id = cnt;
		new->level = s.level;
		new->name = strdup(s.name);
		new->type = strlen(s.type) ? strdup(s.type) : NULL;
		new->offset = le32_to_cpu(s.offset);
		new->size = le32_to_cpu(s.size);
		new->is_array = s.array ? true : false;
		for(i = 0; i < 4; i++)
			new->dims[i] = le32_to_cpu(s.array_dims[i]);
		INIT_LIST_HEAD(&new->children);

		if(new->level == expect_level) {
			assert(parent != NULL);
			list_add_tail(&new->link, &parent->children);
			new->parent = parent;
		} else if (new->level > expect_level) {
			expect_level++;
			parent = last;
			assert(parent != NULL);
			list_add_tail(&new->link, &parent->children);
			new->parent = parent;
		} else if (new->level < expect_level) {
			while(expect_level > new->level) {
				expect_level--;
				parent = parent->parent;
			}
			assert(parent != NULL);
			list_add_tail(&new->link, &parent->children);
			new->parent = parent;
		} else {
			assert(0);
		}

		last = new;
		cnt++;
	}

	print(&root, 0);
}
