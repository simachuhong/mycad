from uuid import uuid4
from mycad.core.sketch import SplineEntity,Sketch,WorkPlaneFrame
from mycad.geom.sketch_profiles import spline_edge
from build123d import Wire
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
from OCP.GeomAbs import GeomAbs_Intersection
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_WIRE
from OCP.TopoDS import TopoDS
source=SplineEntity(uuid4().hex,((0,0),(5,0),(5,5),(10,5)))
sketch=Sketch(uuid4().hex,WorkPlaneFrame.xy(),(source,))
w=Wire([spline_edge(sketch,source)])
for d in (1.,-1.):
 try:
  m=BRepOffsetAPI_MakeOffset(w.wrapped,GeomAbs_Intersection,True)
  m.Perform(d)
  ex=TopExp_Explorer(m.Shape(),TopAbs_WIRE)
  results=[]
  while ex.More():
   out=Wire(TopoDS.Wire_s(ex.Current()))
   results.append((out.is_closed,[(str(e.geom_type),e.length,tuple(e.position_at(0)),tuple(e.position_at(1))) for e in out.order_edges()]))
   ex.Next()
  print(d, m.IsDone(), results)
 except Exception as exc: print(d,type(exc).__name__,str(exc))
