import numpy as np
import pandas as pd
import trimesh as tm
import os
import cv2
import time

from i_grip.utils2 import Bbox, State, Trajectory, Pose, Entity
from i_grip import ObjectPoseEstimators as ope
import matplotlib.colors as mcolors

from i_grip.config import _TLESS_MESH_PATH, _YCVB_MESH_PATH, _TLESS_URDF_PATH, _YCVB_URDF_PATH
class RigidObjectTrajectory(Trajectory):
    
    DEFAULT_DATA_KEYS = [ 'Timestamps', 'x', 'y', 'z', 'qx', 'qy', 'qz', 'qw', 'Extrapolated']
    DEFAULT_ATTRIBUTES  = dict(timestamp=True, pose=True)
    
    def __init__(self, state = None, headers_list = DEFAULT_DATA_KEYS, attributes_dict=DEFAULT_ATTRIBUTES, file = None, dataframe = None, limit_size=None) -> None:
        super().__init__(state, headers_list, attributes_dict, file, dataframe, limit_size)

    def __next__(self):
        if self.current_line_index < len(self.data):
            row = self.data.iloc[self.current_line_index]
            self.current_line_index+=1
            return Pose.from_vector_and_quat(np.array([row['x'], row['y'], row['z']]), np.array([row['qx'], row['qy'], row['qz'], row['qw']])), row['Timestamps']
        else:
            raise ValueError('No more data in trajectory')
    
    def __getitem__(self, index):
        if index < len(self.data):
            row = self.data.iloc[index]
            return Pose.from_vector_and_quat(np.array([row['x'], row['y'], row['z']]), np.array([row['qx'], row['qy'], row['qz'], row['qw']])), row['Timestamps']
        else:
            raise IndexError('Index out of range')
        
class RigidObject(Entity):
    
    MAIN_DATA_KEYS=RigidObjectTrajectory.DEFAULT_DATA_KEYS
    
    LABEL_EXPE_NAMES = {'obj_000002' : 'cheez\'it',
                        'obj_000004' : 'tomato',
                        'obj_000005' : 'mustard',
                        'obj_000012' : 'bleach'}
    _TARGETS_COLORS = ['green',  'orange', 'purple', 'pink', 'brown', 'grey', 'black']
    _OBJECTS_COLORS = [mcolors.to_rgba(c) for c in _TARGETS_COLORS]
    
    # _TLESS_MESH_PATH = '/home/emoullet/Documents/DATA/cosypose/local_data/bop_datasets/tless/models_cad'
    # _YCVB_MESH_PATH = '/home/emoullet/Documents/DATA/cosypose/local_data/bop_datasets/ycbv/models'
    # _TLESS_URDF_PATH = '/home/emoullet/Documents/DATA/cosypose/local_data/urdfs/tless.cad/'
    # _YCVB_URDF_PATH = '/home/emoullet/Documents/DATA/cosypose/local_data/urdfs/ycbv/'
    
    # def __init__(self, dataset = 'tless',  label = None, pose=None, score = None, render_box=None, timestamp = None, trajectory = None) -> None:
    def __init__(self, input,  timestamp = None, dataset = None, label = None, index = 0) -> None:
        super().__init__(timestamp=timestamp)   
        
        self.label = label
        if label in RigidObject.LABEL_EXPE_NAMES:
            self.name = RigidObject.LABEL_EXPE_NAMES[label]
        else:
            self.name = label
            
        print('object '+self.name+ ' discovered')
        
        if isinstance(input, ope.ObjectPoseEstimation):
            self.was_built_from = 'prediction'
            if timestamp is None:
                raise ValueError('timestamp must be provided if pose is provided')
            self.state = RigidObjectState.from_pose(input.pose, timestamp, position_factor=1000, flip_pos_y=True)
            # self.trajectory = RigidObjectTrajectory.from_state(self.state)
            self.score = input.score
            self.render_box = Bbox(self.label, input.render_box)
        elif isinstance(input, pd.DataFrame):
            self.was_built_from = 'trajectory'
            # self.trajectory = RigidObjectTrajectory.from_dataframe(input)
            # first_pose, first_timestamp = self.trajectory[0]
            # self.state = RigidObjectState.from_pose(first_pose, first_timestamp)
            self.state = RigidObjectState.from_dataframe(input)
            self.score = None
            self.render_box = None
        else:
            raise ValueError('input must be either an ObjectPoseEstimation or a dataframe')
         
            
        self.dataset = dataset
        if(dataset == "ycbv"):
            self.mesh_path = str(_YCVB_MESH_PATH)
            self.urdf_path = str(_YCVB_URDF_PATH)
        elif(dataset == "tless"):
            self.mesh_path = str(_TLESS_MESH_PATH)
            self.urdf_path = str(_TLESS_URDF_PATH)
        else:
            raise ValueError('dataset must be either ycbv or tless')
        print(f'mesh path : {self.mesh_path}')
        
        self.mesh_color = RigidObject._OBJECTS_COLORS[index]
        self.default_color = (0, 255, 0)
        
        self.load_simplified = True
        if self.load_simplified:
            if not os.path.exists(self.mesh_path+'_simplified'):
                print('simplified meshes not found, falling back to original meshes')
                self.load_simplified = False
        
        self.distances={}
        self.nb_updates = 10
        
        self.mesh_pos = np.array([0,0,0])
        self.mesh_transform = np.identity(4)
        self.inv_mesh_transform = np.identity(4)
        self.load_mesh()
        self.update_mesh()
        
        self.is_targeted = False
        self.targeter = None
        self.target_info = None
        if self.was_built_from == 'prediction':
            self.update_display()
        
        # self.trajectory = pd.DataFrame(columns=['Timestamps', 'x', 'y', 'z', 'qx', 'qy', 'qz', 'qw', 'is_targeted', 'targeter', 'time_of_impact', 'grip'])
    
    @classmethod
    def from_prediction(cls, prediction, timestamp):
        return cls(dataset=prediction.dataset, label = prediction.label, pose = prediction.pose, score = prediction.score, render_box = prediction.render_box, timestamp = timestamp)
    
    @classmethod
    def from_trajectory(cls, label, trajectory):
        return cls(label = label, trajectory=trajectory)
    
    def load_mesh(self):
        try :
            if self.load_simplified:
                self.mesh = tm.load_mesh(self.mesh_path+'_simplified/'+self.label+'.ply')
                print('MESH LOADED : ' + self.mesh_path+'_simplified/'+self.label+'.ply')
            else:
                self.mesh = tm.load_mesh(self.mesh_path+'/'+self.label+'.ply')
                print('MESH LOADED : ' + self.mesh_path+'/'+self.label+'.ply')
            self.mesh.visual.face_colors = self.mesh_color
            print(f'vertices : {self.mesh.vertices}')
            print(f'faces : {self.mesh.faces}')
            print(f'normals : {self.mesh.vertex_normals}')
            print(f'center of mass : {self.mesh.center_mass}')
            
        except:
            self.mesh = None
            print(self.mesh_path)
            print('MESH LOADING FAILED')
        self.mesh.mutable = True
        self.original_mesh = self.mesh.copy()
        self.first = True
        self.z = 0
    
    def load_urdf(self):
        self.mesh = tm.load_mesh(self.urdf_path+self.label+'/'+self.label+'.obj')
        print('URDF LOADED : ' + self.urdf_path+self.label+'/'+self.label+'.obj')
        exit()

    
    def update(self, new_prediction, timestamp = None):
        # t = time.time()
        self.state.update(new_prediction.pose, timestamp = timestamp)
        # print(f'object update time : {(time.time()-t)*1000:.2f}ms')
        # t = time.time()
        self.render_box.update_coordinates(new_prediction.render_box)
        # print(f'object update render box time : {(time.time()-t)*1000:.2f}ms')
        # t = time.time()
        if self.nb_updates <=15:
            self.nb_updates+=2
        self.update_trajectory()
        # print(f'object update trajectory time : {(time.time()-t)*1000:.2f}ms')
        self.set_mesh_updated(False)
    
    def update_pose(self, translation_vector, quaternion):
        self.pose.update_from_vector_and_quat(translation_vector, quaternion)

    def update_from_trajectory(self, index = None):
        if index is None:
            print(f'object {self.label} update from trajectory')
            pose, timestamp = self.state.__next__()
        else:
            pose, timestamp = self.state[index]
        self.state.update(pose)
        self.state.propagate(timestamp)
        self.set_mesh_updated(False)
        
    def update_mesh(self):
        # print('update obj mesh try')
        if self.was_mesh_updated():
            return
        self.mesh_pos = self.state.pose_filtered.position.v*np.array([-1,1,1])
        # mesh_orient_quat = [self.pose.orientation.q[i] for i in range(4)]
        # mesh_orient_angles = self.pose.orientation.v*np.array([-1,-1,-1])+np.pi*np.array([1  ,1,0])
        mesh_orient_angles = self.state.pose_filtered.orientation.v*np.array([1,1,1])+np.pi*np.array([0 ,0,1])
        # x_reflection_matrix = tm.transformations.reflection_matrix(np.array([0,0,0]), np.array([1,0,0]))
        #mesh_transform = tm.transformations.translation_matrix(mesh_pos)  @ tm.transformations.quaternion_matrix(mesh_orient_quat)
        rot_mat = tm.transformations.euler_matrix(mesh_orient_angles[0],mesh_orient_angles[1],mesh_orient_angles[2])
        self.mesh_transform = np.identity(4)
        self.mesh_transform[2,3]=self.z
        self.z+=5
        print(f'object {self.label} mesh transform : {self.mesh_transform}')
        
        self.set_transform_tm(self.mesh_transform)
        print('update obj mesh done')
        self.inv_mesh_transform = np.linalg.inv(self.mesh_transform)
        self.set_mesh_updated(True)
        
    def set_transform(self, transform):
        t = time.time()
        matrix = np.asanyarray(transform, order="C", dtype=np.float64)
        has_rotation = not tm.util.allclose(matrix[:3, :3], np.eye(3), atol=1e-6)
        if 'center_mass' in self.mesh._data:
            self.mesh.center_mass = self.original_mesh.center_mass
        if has_rotation and "face_normals" in self.mesh._cache:
            self.mesh.face_normals = self.original_mesh.face_normals
        if has_rotation and "vertex_normals" in self.mesh._cache:
            self.mesh.vertex_normals = self.original_mesh.vertex_normals
        if has_rotation and tm.transformations.flips_winding( matrix):
            self.mesh.faces = self.original_mesh.faces
        self.mesh.vertices = self.original_mesh.vertices
        self.mesh.apply_transform(transform)
        print(f'object {self.label} mesh transform applied in {(time.time()-t)*1000:.2f}ms')
    
    def set_transform_tm(self, matrix):
        
        """
        Transform mesh by a homogeneous transformation matrix.

        Does the bookkeeping to avoid recomputing things so this function
        should be used rather than directly modifying self.vertices
        if possible.

        Parameters
        ------------
        matrix : (4, 4) float
          Homogeneous transformation matrix
        """
        # get c-order float64 matrix
        matrix = np.asanyarray(matrix, order="C", dtype=np.float64)

        # only support homogeneous transformations
        if matrix.shape != (4, 4):
            raise ValueError("Transformation matrix must be (4, 4)!")

        # exit early if we've been passed an identity matrix
        # np.allclose is surprisingly slow so do this test
        elif tm.util.allclose(matrix, np.eye(4), 1e-8):
            return 

        # new vertex positions
        new_vertices = tm.transformations.transform_points(self.original_mesh.vertices, matrix=matrix)

        # check to see if the matrix has rotation
        # rather than just translation
        has_rotation = not tm.util.allclose(matrix[:3, :3], np.eye(3), atol=1e-6)

        # transform overridden center of mass
        if "center_mass" in self.mesh._data:
            center_mass = [self.original_mesh._data["center_mass"]]
            self.mesh.center_mass = tm.transformations.transform_points(
                center_mass,
                matrix,
            )[0]

        # preserve face normals if we have them stored
        if has_rotation and "face_normals" in self.mesh._cache:
            # transform face normals by rotation component
            self.mesh._cache.cache["face_normals"] = tm.util.unitize(
                tm.transformations.transform_points(
                    self.original_mesh.face_normals, matrix=matrix, translate=False
                )
            )

        # preserve vertex normals if we have them stored
        if has_rotation and "vertex_normals" in self.mesh._cache:
            self.mesh._cache.cache["vertex_normals"] = tm.util.unitize(
                tm.transformations.transform_points(
                    self.original_mesh.vertex_normals, matrix=matrix, translate=False
                )
            )

        # if transformation flips winding of triangles
        if has_rotation and tm.transformations.flips_winding(matrix):
            # log.debug("transform flips winding")
            # fliplr will make array non C contiguous
            # which will cause hashes to be more
            # expensive than necessary so wrap
            self.mesh.faces = np.ascontiguousarray(np.fliplr(self.original_mesh.faces))

        # assign the new values
        self.mesh.vertices = new_vertices

        # preserve normals and topology in cache
        # while dumping everything else
        self.mesh._cache.clear(
            exclude={
                "face_normals",  # transformed by us
                "vertex_normals",  # also transformed by us
                "face_adjacency",  # topological
                "face_adjacency_edges",
                "face_adjacency_unshared",
                "edges",
                "edges_face",
                "edges_sorted",
                "edges_unique",
                "edges_unique_idx",
                "edges_unique_inverse",
                "edges_sparse",
                "body_count",
                "faces_unique_edges",
                "euler_number",
            }
        )
        # set the cache ID with the current hash value
        self.mesh._cache.id_set()
        return 
    
    def write(self, img):
        text = self.name 
        x = self.render_box.corner1[0]
        y = self.render_box.corner1[1]-60
        dy = 15
        cv2.rectangle(img, (x,y-20), (self.render_box.corner2[0],self.render_box.corner1[1]), (200,200,200), -1)
        cv2.putText(img, text , (x,y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.color)    
        if self.is_targeted:
            text ='Trgt by : ' + self.targeter.label 
            y+=dy
            cv2.putText(img, text , (x,y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.color)  
            text = 'tbi : '+str(self.target_info.get_time_of_impact()) + 'ms'
            y+=dy
            cv2.putText(img, text , (x,y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.color)  
            text ='GRIP : '+self.target_info.get_grip()
            y+=dy
            cv2.putText(img, text , (x,y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.color)  

    def write_dist(self, img):
        text = self.label
        x = self.render_box.corner1[0]
        y = self.render_box.corner2[1]
        dy = 20
        cv2.rectangle(img, (x,y), (self.render_box.corner2[0]+30,y+50), (200,200,200), -1)
        for k, d in self.distances.items():
            cv2.putText(img, 'd-'+k+' : '+str(int(d)) +' cm' , (x,y+20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, self.color)    
            y+=dy

    def render(self, img, bbox = True, txt=False, dist=False, overlay=False):
        if self.was_built_from != 'prediction':
            return
        self.update_display()
        if txt:
            self.write(img)
        if bbox:
            self.render_box.draw(img)
        if dist:
            self.write_dist(img)
        if overlay:
            pass
    
    def distance_to(self, hand):
        time_ = time.time()
        print(hand.get_mesh_position())
        (closest_points,
        distances,
        triangle_id) = self.mesh.nearest.on_surface(hand.get_mesh_position())
        elapsed = time.time()-time_
        print('elapsed : ', elapsed*1000)
        self.distances[hand.label] = np.linalg.norm(100*self.pose.position.v - 0.1*hand.xyz)


    def set_target_info(self, info):
        self.is_targeted = info[0]
        self.targeter = info[1]
        self.target_info = info[2]
        #if self.is_targeted:
        #    print(self.label, 'is targeted by ', self.targeter.label, 'in', self.target_info.get_time_of_impact())

    def update_display(self):
        if self.is_targeted:
            self.color = self.targeter.text_color
            thickness = 4
        else:
            self.color = self.default_color
            thickness = 2
        self.render_box.update_display(self.color, thickness)
        # print('DISPLAY UPDATED', time.time())
    
    # def __str__(self):
    #     out = 'label: ' + str(self.label) + '\n pose: {' +str(self.pose)+'} \n nb_updates: '+str(self.nb_updates)
    #     return out
    
    def get_position(self):
        return self.state.pose.position
   
class RigidObjectState(State):
    def __init__(self, pose = None, timestamp=None, position_factor=1, flip_pos_y = False, orientation_factor=1, trajectory = None) -> None:
        super().__init__()
        self.position_factor = position_factor
        self.orientation_factor = orientation_factor
        self.flip_pos_y = flip_pos_y
        if pose is None or timestamp is None:
            self.pose = None
            self.last_timestamp = None
        else:
            self.pose = Pose(pose, position_factor, orientation_factor, flip_pos_y=flip_pos_y)
            self.pose_filtered = Pose(pose, position_factor, orientation_factor, filtered=True, flip_pos_y=flip_pos_y)
            self.last_timestamp = timestamp
        if trajectory is None:
            self.trajectory = RigidObjectTrajectory.from_state(self)
        else:
            self.trajectory = trajectory
    
    @classmethod
    def from_pose(cls, pose, timestamp, position_factor=1, flip_pos_y = False, orientation_factor=1):
        return cls(pose, timestamp, position_factor, flip_pos_y, orientation_factor)
    
    @classmethod
    def from_dataframe(cls, df:pd.DataFrame, position_factor=1, flip_pos_y = False, orientation_factor=1):
        trajectory = RigidObjectTrajectory.from_dataframe(df)
        first_position, first_timestamp = trajectory[0]
        return cls(first_position, timestamp=first_timestamp, position_factor=position_factor, flip_pos_y=flip_pos_y, orientation_factor=orientation_factor, trajectory=trajectory)
    
    def update(self, pose, timestamp=None):
        self.pose.update(pose, flip_pos_y=self.flip_pos_y)
        self.pose_filtered.update(pose, flip_pos_y=self.flip_pos_y)
        self.last_timestamp = timestamp
    
    def update_from_vector_and_quat(self, translation_vector, quaternion, timestamp=None):
        self.pose.update_from_vector_and_quat(translation_vector, quaternion, flip_pos_y=self.flip_pos_y)
        self.pose_filtered.update_from_vector_and_quat(translation_vector, quaternion, flip_pos_y=self.flip_pos_y)
        self.last_timestamp = timestamp
    
    def propagate(self, timestamp):
        # self.last_timestamp = timestamp
        pass
        #TODO: propagate pose for tracking moving objects
    
    def as_list(self, timestamp=True, pose=True, pose_filtered=False):
        repr_list = []
        if timestamp:
            repr_list.append(self.last_timestamp)
        if pose:
            repr_list += self.pose.as_list()
        if pose_filtered:
            repr_list += self.pose_filtered.as_list()
        return repr_list
    
    def __next__(self):
        return self.trajectory.__next__()

    def __getitem__(self, index):
        return self.trajectory[index]
    
    def __str__(self) -> str:
        return f'HandState : {self.position_filtered}'
    
    def __repr__(self) -> str:
        return self.__str__()