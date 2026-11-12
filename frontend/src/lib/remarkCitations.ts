// remark plugin: turn [3] or [1, 3] in plain text into #cite-n links, which AnswerMarkdown
// renders as citation chips. Text inside code, links and other non-text nodes is untouched.

interface MdNode {
  type: string
  value?: string
  url?: string
  children?: MdNode[]
}

const CITE = /\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]/g
const SKIP = new Set(['link', 'linkReference', 'inlineCode', 'code', 'definition'])

function split(text: string): MdNode[] {
  const out: MdNode[] = []
  let last = 0
  for (const m of text.matchAll(CITE)) {
    const at = m.index ?? 0
    if (at > last) out.push({ type: 'text', value: text.slice(last, at) })
    for (const n of m[1].split(',').map((x) => x.trim())) {
      out.push({ type: 'link', url: `#cite-${n}`, children: [{ type: 'text', value: n }] })
    }
    last = at + m[0].length
  }
  if (last < text.length) out.push({ type: 'text', value: text.slice(last) })
  return out
}

function walk(node: MdNode) {
  if (!node.children) return
  node.children = node.children.flatMap((child) => {
    if (child.type === 'text' && child.value && CITE.test(child.value)) {
      CITE.lastIndex = 0
      return split(child.value)
    }
    CITE.lastIndex = 0
    if (!SKIP.has(child.type)) walk(child)
    return [child]
  })
}

export default function remarkCitations() {
  return (tree: MdNode) => walk(tree)
}
