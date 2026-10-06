"""Small synthetic CAD scene; no real project geometry in tests."""
import base64
import struct


def buffer(values, dtype):
    code = 'f' if dtype == 'float32' else 'i'
    return {'shape': [len(values)], 'dtype': dtype, 'codec': 'b64',
            'buffer': base64.b64encode(struct.pack('<' + code * len(values), *values)).decode()}


def box_scene(width=10):
    corners = [(0,0,0), (width,0,0), (width,10,0), (0,10,0),
               (0,0,10), (width,0,10), (width,10,10), (0,10,10)]
    faces = [(0,3,2,1), (4,5,6,7), (0,1,5,4), (3,7,6,2), (0,4,7,3), (1,2,6,5)]
    normals = [(0,0,-1), (0,0,1), (0,-1,0), (0,1,0), (-1,0,0), (1,0,0)]
    vertices, triangles, ns = [], [], []
    for face, normal in zip(faces, normals):
        offset = len(vertices)//3
        for i in face:
            vertices.extend(corners[i]); ns.extend(normal)
        triangles.extend(offset+i for i in (0,1,2,0,2,3))
    edges = [(0,1), (1,2), (2,3), (3,0), (4,5), (5,6), (6,7), (7,4), (0,4), (1,5), (2,6), (3,7)]
    instance = {k: buffer(v, dtype) for k, v, dtype in [
        ('vertices', vertices, 'float32'), ('triangles', triangles, 'int32'),
        ('normals', ns, 'float32'), ('edges', [n for edge in edges for i in edge for n in corners[i]], 'float32'),
        ('obj_vertices', [n for p in corners for n in p], 'float32'),
        ('face_types', [0]*6, 'int32'), ('edge_types', [0]*12, 'int32'),
        ('triangles_per_face', [2]*6, 'int32'), ('segments_per_edge', [1]*12, 'int32')]}
    parts = [dict(id='/Assembly/'+name, type='shapes', subtype='solid', name=name, shape={'ref': 0},
                  state=[1,1], color=color, alpha=1.0, material=None,
                  loc=[[x,0,0],[0,0,0,1]], renderback=False, accuracy=None, bb=None)
             for name,x,color in [('Block A',0,'#659bd3'),('Block B',25,'#dbb873')]]
    return {'type': 'data', 'data': {'instances': [instance], 'shapes': {
        'version': 3, 'id': '/Assembly', 'name': 'Assembly', 'parts': parts,
        'loc': [[0,0,0],[0,0,0,1]], 'bb': {'xmin':0, 'xmax':25+width, 'ymin':0,'ymax':10,'zmin':0,'zmax':10}}},
        'config': {}, 'meta': {'name': 'Review test', 'owner_session': 'test-owner', 'units': 'mm'}}
