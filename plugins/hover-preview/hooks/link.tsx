// The surface module of a path under a reply: it says when the pointer is on it and when it leaves,
// so the hooks module shows that path's preview, and when it is clicked, so it shows the path in the
// file manager (opens it, with alt).
import type { ClientModule } from 'claude-code'

type Props = { label: string; path: string; line?: number }

const Link: ClientModule<Props, { isOver: boolean; isPressed?: boolean }> = (props, surface) => {
  const where = { path: props.path, ...(props.line !== undefined && { line: props.line }) }
  surface.onPointer(event => {
    if (event.type === 'down') {
      if (event.button === 'left') surface.setState({ isOver: true, isPressed: true })
      return
    }
    if (event.type === 'up') {
      const isInside = surface.columns === 0 || (event.x >= 0 && event.y >= 0 && event.x < surface.columns && event.y < surface.rows)
      if (surface.state?.isPressed && isInside) surface.post({ ...where, isOver: true, isClicked: true, ...(event.alt && { isAlt: true }) })
      surface.setState({ isOver: isInside })
      return
    }
    const isOver = event.type !== 'leave'
    surface.post({ ...where, isOver })
    if (isOver !== (surface.state?.isOver ?? false)) surface.setState({ isOver, isPressed: surface.state?.isPressed })
  })
  const { Text } = surface.elements
  return <Text color="permission" underline={surface.state?.isOver === true}>{props.label}</Text>
}

export default Link
