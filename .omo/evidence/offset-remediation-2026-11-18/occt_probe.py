from build123d import Edge, Wire
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
from OCP.GeomAbs import GeomAbs_Intersection
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_WIRE
from OCP.TopoDS import TopoDS
points=[(0,0),(4,0),(4,1),(6,1),(6,0),(10,0),(10,4),(6,4),(6,3),(4,3),(4,4),(0,4)]
w=Wire([Edge.make_line((*a,0),(*b,0)) for a,b in zip(points,points[1:]+points[:1])])
for d in [-.5,-1.1,1.1]:
 try:
  m=BRepOffsetAPI_MakeOffset(w.wrapped,GeomAbs_Intersection,False)
  m.Perform(d)
  x=TopExp_Explorer(m.Shape(),TopAbs_WIRE)
  ws=[]
  while x.More():
   w2=Wire(TopoDS.Wire_s(x.Current()))
   ws.append((len(w2.edges()),w2.length,w2.is_closed))
   x.Next()
  print(d, m.IsDone(), ws)
 except Exception as exc: print(d,type(exc).__name__, str(exc))
