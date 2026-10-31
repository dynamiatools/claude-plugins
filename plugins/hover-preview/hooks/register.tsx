import type { Register } from 'claude-code'

import { registerImages } from './images'
import { registerLinks } from './links'

// A plugin has one hooks module: it joins the two previews, the pasted images above the prompt and
// the paths under a reply.
export const register: Register = (on, options) => {
  registerImages(on, options)
  registerLinks(on, options)
}
